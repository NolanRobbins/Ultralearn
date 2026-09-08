"""Tests for the HTTP service."""

import pytest
from fastapi.testclient import TestClient

from ultralearn.api import create_app
from ultralearn.config import AppConfig


@pytest.fixture
def client(tmp_path):
    app = create_app(AppConfig(db_path=tmp_path / "api.db", provider="manual"))
    state = app.state.ultralearn
    with TestClient(app) as test_client:
        test_client.headers["X-Ultralearn-Token"] = state.token
        test_client.state = state
        yield test_client


@pytest.fixture
def seeded(client):
    """One concept with one written question, ready to be answered."""

    db = client.state.db
    concept_id = db.find_or_create_concept(
        "Vanishing gradients", "Saturating activations shrink gradients.", "dl"
    )
    question_id = db.add_question(
        concept_id=concept_id,
        source_id=None,
        chunk_id=None,
        question_type="short_answer",
        prompt="Why do gradients vanish in a deep sigmoid network?",
        options=[],
        answer={"text": "Saturated sigmoids have near-zero derivative, multiplied over depth."},
        explanation="The chain rule multiplies many sub-one factors.",
        bloom="analyze",
    )
    return {"concept_id": concept_id, "question_id": question_id}


def test_api_requires_the_launch_token(tmp_path):
    app = create_app(AppConfig(db_path=tmp_path / "api.db", provider="manual"))
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/today").status_code == 401


def test_wrong_token_is_rejected(client):
    response = client.get("/api/today", headers={"X-Ultralearn-Token": "guessed"})
    assert response.status_code == 401


def test_today_reports_an_empty_library_without_erroring(client):
    body = client.get("/api/today").json()
    assert body["due"] == 0
    assert body["streak_days"] == 0
    assert len(body["recent_days"]) == 30


def test_session_serves_a_written_question(client, seeded):
    items = client.post("/api/session", params={"size": 5}).json()["items"]
    assert len(items) == 1
    assert items[0]["question_id" if "question_id" in items[0] else "id"] == seeded["question_id"]
    # Free recall is the default: a short_answer question must not offer options.
    assert items[0]["written"] is True
    assert items[0]["options"] == []


def test_reveal_returns_the_reference_answer(client, seeded):
    body = client.get(f"/api/questions/{seeded['question_id']}/reveal").json()
    assert "near-zero derivative" in body["expected_answer"]
    assert body["explanation"]


def test_recording_a_review_advances_the_schedule(client, seeded):
    response = client.post(
        "/api/review",
        json={
            "concept_id": seeded["concept_id"],
            "question_id": seeded["question_id"],
            "correct": True,
            "confidence": 4,
            "mode": "due",
            "score": 4,
            "graded_by": "examiner",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["mastery"] > 0
    assert client.get("/api/today").json()["reviewed_today"] == 1


def test_a_named_misconception_is_stored_and_resurfaces(client, seeded):
    client.post(
        "/api/review",
        json={
            "concept_id": seeded["concept_id"],
            "question_id": seeded["question_id"],
            "correct": False,
            "confidence": 4,
            "misconception": "Believes depth alone causes vanishing gradients.",
        },
    )
    assert client.get("/api/today").json()["open_misconceptions"] == 1

    # It comes back attached to the question, so the learner sees it again.
    items = client.post("/api/session").json()["items"]
    assert items[0]["misconceptions"] == ["Believes depth alone causes vanishing gradients."]

    drill = client.post("/api/session/drill").json()
    assert drill["total"] == 1
    assert drill["items"][0]["mode"] == "drill"


def test_a_clean_answer_retires_the_misconception(client, seeded):
    payload = {
        "concept_id": seeded["concept_id"],
        "question_id": seeded["question_id"],
        "correct": False,
        "confidence": 3,
        "misconception": "Confuses saturation with depth.",
    }
    client.post("/api/review", json=payload)
    assert client.get("/api/today").json()["open_misconceptions"] == 1

    body = client.post(
        "/api/review",
        json={**payload, "correct": True, "misconception": ""},
    ).json()
    assert body["resolved_misconceptions"] == 1
    assert client.get("/api/today").json()["open_misconceptions"] == 0


def test_grading_without_a_provider_does_not_fake_a_pass(client, seeded):
    body = client.post(
        "/api/grade",
        json={"question_id": seeded["question_id"], "answer": "something vague", "confidence": 3},
    ).json()
    assert body["graded_by"] == "self"
    assert body["verdict"] != "correct"
    assert body["expected_answer"]


def test_ingest_returns_a_job_immediately(client):
    """The request must not wait on the provider."""

    response = client.post(
        "/api/ingest",
        json={"text": "# Notes\nGradients shrink through saturating activations.",
              "title": "Notes", "generate": False},
    )
    assert response.status_code == 200
    job = response.json()
    assert job["status"] in {"queued", "running"}
    assert job["label"] == "Notes"

    assert client.get("/api/jobs").json()[0]["id"] == job["id"]


def test_empty_ingest_is_rejected(client):
    assert client.post("/api/ingest", json={"text": "  "}).status_code == 400


def test_job_stream_requires_the_token(client):
    assert client.get("/api/jobs/stream/events", params={"token": "wrong"}).status_code == 401


def test_search_finds_ingested_concepts(client, seeded):
    hits = client.get("/api/search", params={"q": "vanishing gradients"}).json()
    assert any("Vanishing" in hit["title"] for hit in hits)


def test_stats_exposes_the_learner_model(client, seeded):
    body = client.get("/api/stats").json()
    assert set(body) >= {"totals", "topic_mastery", "calibration", "weak_spots", "misconceptions"}


def test_missing_question_is_a_404(client):
    assert client.get("/api/questions/999/reveal").status_code == 404
