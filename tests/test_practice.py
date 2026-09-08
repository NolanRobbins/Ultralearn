from datetime import date, timedelta

from ultralearn.db import KnowledgeDB


def make_db(tmp_path) -> KnowledgeDB:
    db = KnowledgeDB(tmp_path / "test.db")
    db.initialize()
    return db


def concept_with_question(db: KnowledgeDB, due: str) -> int:
    concept_id = db.find_or_create_concept("Pot odds", "Price of a call vs pot size.", "poker", due=due)
    db.add_question(
        concept_id=concept_id,
        source_id=None,
        chunk_id=None,
        question_type="single_mcq",
        prompt="You face a half-pot bet. What equity do you need to call?",
        options=["20%", "25%", "33%", "50%"],
        answer={"index": 1},
        explanation="Half-pot lays 3:1, so 25%.",
        bloom="apply",
    )
    return concept_id


def test_practice_review_logs_but_keeps_schedule(tmp_path):
    db = make_db(tmp_path)
    future = (date.today() + timedelta(days=5)).isoformat()
    concept_id = concept_with_question(db, due=future)

    db.record_review(
        concept_id=concept_id,
        question_id=None,
        correct=True,
        confidence=4,
        quality=5,
        update_schedule=False,
    )

    concept = db.get_concept(concept_id)
    assert concept.due == future  # schedule untouched
    assert concept.repetitions == 0
    assert concept.mastery > 0  # but the attempt counted
    assert db.stats()["reviews"] == 1


def test_practice_miss_pulls_concept_back_to_due(tmp_path):
    db = make_db(tmp_path)
    future = (date.today() + timedelta(days=5)).isoformat()
    concept_id = concept_with_question(db, due=future)

    db.record_review(
        concept_id=concept_id,
        question_id=None,
        correct=False,
        confidence=5,
        quality=0,
        update_schedule=False,
    )

    concept = db.get_concept(concept_id)
    assert concept.due == date.today().isoformat()
    assert concept.ease == 2.5  # ease untouched by practice


def test_get_practice_concepts_excludes_ids(tmp_path):
    db = make_db(tmp_path)
    future = (date.today() + timedelta(days=5)).isoformat()
    first = concept_with_question(db, due=future)
    second = db.find_or_create_concept("Implied odds", "Future winnings justify a call.", "poker", due=future)

    practice = db.get_practice_concepts(limit=10, exclude_ids=[first])
    ids = [concept.id for concept in practice]
    assert first not in ids
    assert second in ids
