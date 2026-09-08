import json
import sqlite3
from pathlib import Path

from ultralearn.db import KnowledgeDB


def test_legacy_cards_migrate_to_concepts_questions_and_reviews(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT NOT NULL,
            source TEXT,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            answer_index INTEGER NOT NULL,
            explanation TEXT,
            bloom TEXT,
            ease REAL NOT NULL DEFAULT 2.5,
            interval INTEGER NOT NULL DEFAULT 0,
            repetitions INTEGER NOT NULL DEFAULT 0,
            due TEXT NOT NULL,
            created TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            correct INTEGER NOT NULL,
            confidence INTEGER NOT NULL,
            quality INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """INSERT INTO cards
           (tag, source, question, options, answer_index, explanation, bloom, ease, interval, repetitions, due, created)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "dl",
            "Prince Ch.3",
            "Why does backpropagation rely on the chain rule?",
            json.dumps(["local gradients", "dropout", "batching", "regularization"]),
            0,
            "It composes gradients through nested functions.",
            "apply",
            2.2,
            6,
            2,
            "2026-07-01",
            "2026-06-01",
        ),
    )
    conn.execute(
        "INSERT INTO reviews (card_id, ts, correct, confidence, quality) VALUES (1, '2026-06-02T00:00:00', 1, 4, 5)"
    )
    conn.commit()
    conn.close()

    db = KnowledgeDB(db_path)
    db.initialize()

    with sqlite3.connect(db_path) as check:
        check.row_factory = sqlite3.Row
        assert check.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"] == 1
        assert check.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"] == 1
        assert check.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"] == 1
        concept = check.execute("SELECT * FROM concepts").fetchone()
        assert concept["due"] == "2026-07-01"
        assert concept["repetitions"] == 2
        assert check.execute("SELECT name FROM sqlite_master WHERE name='legacy_reviews'").fetchone()

    db.initialize()
    with sqlite3.connect(db_path) as check:
        assert check.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
