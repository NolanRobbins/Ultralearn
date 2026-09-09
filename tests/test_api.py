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
    assert all("via" in hit for hit in hits)


def test_focus_session_returns_the_matching_concept(client, seeded):
    items = client.post("/api/session/focus", params={"q": "vanishing gradients"}).json()["items"]
    assert items
    assert items[0]["concept_id"] == seeded["concept_id"]
    assert items[0]["mode"] == "practice"


def test_empty_focus_is_rejected(client):
    assert client.post("/api/session/focus", params={"q": "  "}).status_code == 400


def test_generate_from_source_queues_a_job(client, seeded):
    source_id = client.state.db.add_source("note", "Notes")
    client.state.db.add_content(source_id, "Saturating activations shrink gradients.")
    response = client.post(f"/api/sources/{source_id}/generate")
    assert response.status_code == 200
    assert response.json()["kind"] == "generate"
    assert response.json()["status"] in {"queued", "running"}


def test_generate_from_missing_source_is_a_404(client):
    assert client.post("/api/sources/999/generate").status_code == 404


def test_focus_generate_queues_a_job(client, seeded):
    response = client.post("/api/focus/generate", params={"q": "vanishing gradients"})
    assert response.status_code == 200
    assert response.json()["kind"] == "generate_focus"


def test_folder_ingest_queues_a_folder_job(client, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "one.md").write_text("# One\nGradients shrink.")
    response = client.post("/api/ingest", json={"folder": str(folder), "generate": False})
    assert response.status_code == 200
    assert response.json()["kind"] == "ingest_folder"


def test_stats_exposes_the_learner_model(client, seeded):
    body = client.get("/api/stats").json()
    assert set(body) >= {"totals", "topic_mastery", "calibration", "weak_spots", "misconceptions"}


def test_stats_calibration_uses_numeric_confidence_keys(client, seeded):
    client.post(
        "/api/review",
        json={
            "concept_id": seeded["concept_id"],
            "question_id": seeded["question_id"],
            "correct": True,
            "confidence": 4,
            "mode": "due",
        },
    )
    calibration = client.get("/api/stats").json()["calibration"]
    assert calibration["4"] == 1.0
    assert "conf 4" not in calibration


def test_mastered_concepts_are_not_listed_as_weak_spots(client, seeded):
    for _ in range(6):
        client.post(
            "/api/review",
            json={
                "concept_id": seeded["concept_id"],
                "question_id": seeded["question_id"],
                "correct": True,
                "confidence": 5,
                "mode": "due",
            },
        )
    stats = client.get("/api/stats").json()
    concept = next(
        row for row in client.get("/api/concepts").json() if row["id"] == seeded["concept_id"]
    )
    assert concept["mastery"] >= 0.75
    assert all(row["id"] != seeded["concept_id"] for row in stats["weak_spots"])


def test_missing_question_is_a_404(client):
    assert client.get("/api/questions/999/reveal").status_code == 404


def test_cursor_health_explains_a_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr("ultralearn.config.LOCAL_ENV_PATH", tmp_path / "env")
    app = create_app(AppConfig(db_path=tmp_path / "cursor.db", provider="cursor"))
    with TestClient(app) as client:
        client.headers["X-Ultralearn-Token"] = app.state.ultralearn.token
        body = client.get("/api/health").json()
        assert body["ready"] is False
        assert "CURSOR_API_KEY" in body["message"]
        settings = client.get("/api/settings").json()
        assert settings["cursor_key_configured"] is False
        assert "cursor_key" not in settings

        client.post("/api/settings", json={"provider": "cursor", "cursor_key": "cursor_secret"})
        stored = client.get("/api/settings").json()
        assert stored["cursor_key_configured"] is True
        assert stored["provider"] == "cursor"
        assert "cursor_secret" not in str(stored)
        saved = (tmp_path / "env").read_text(encoding="utf-8")
        assert "ULTRALEARN_PROVIDER=cursor" in saved
        assert "cursor_secret" in saved


def test_code_problems_are_listed_without_hidden_tests(client):
    problems = client.get("/api/code/problems").json()
    assert len(problems) >= 10
    assert all("tests" not in problem for problem in problems)
    body = client.get(f"/api/code/problems/{problems[0]['id']}").json()
    assert "tests" not in body
    assert body["starter"]


def test_code_run_executes_hidden_checks(client):
    problems = client.get("/api/code/problems").json()
    problem = next(item for item in problems if item["slug"] == "mse-loss")
    result = client.post(
        "/api/code/run",
        json={"problem_id": problem["id"], "code": problem["starter"]},
    ).json()
    assert result["passed"] is False
    assert result["checks"] or result["error"] or result["timed_out"]


def test_math_formulas_hide_answers_until_graded(client):
    formulas = client.get("/api/math/formulas").json()
    assert len(formulas) >= 10
    softmax = next(item for item in formulas if item["slug"] == "softmax")
    assert "spoken" not in softmax
    assert all("answer" not in blank and "why" not in blank for blank in softmax["blanks"])
    assert all("why" not in term for term in softmax["terms"])
    body = client.get(f"/api/math/formulas/{softmax['id']}").json()
    assert "spoken" not in body
    assert "key_phrases" not in body

    spoken = client.post(
        "/api/math/grade",
        json={
            "formula_id": softmax["id"],
            "mode": "speak",
            "spoken": (
                "Softmax turns logits into a probability by exponentiating each "
                "one and dividing by the sum of those exponentials."
            ),
        },
    ).json()
    assert spoken["passed"] is True
    assert "probability" in spoken["spoken"].lower() or spoken["spoken"]

    fill = client.post(
        "/api/math/grade",
        json={
            "formula_id": softmax["id"],
            "mode": "fill",
            "blanks": {"num": "exp(z_i)"},
        },
    ).json()
    assert fill["passed"] is True
    assert fill["blank_results"][0]["answer"]

    why = client.post(
        "/api/math/grade",
        json={
            "formula_id": softmax["id"],
            "mode": "why",
            "term_symbol": "z_i",
            "why": "It is the raw unconstrained score for that class before it becomes a probability.",
        },
    ).json()
    assert why["term_why"]
    assert why["passed"] is True

    today = client.get("/api/today").json()
    assert today["math_formulas"] >= 10


