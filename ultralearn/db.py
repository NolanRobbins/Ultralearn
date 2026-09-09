"""SQLite storage for the concept-centered Ultralearn knowledge base."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_DB_PATH
from .dedup import QuestionDeduper, fingerprint, normalize_text
from .embeddings import cosine, get_embedder, pack_vector, unpack_vector
from .models import Concept, ProviderQuestion, Question
from .scheduler import schedule_review_state


DEFAULT_TOPICS = {
    "dl": "Deep Learning",
    "math": "Math",
    "gpu": "GPU Optimization",
    "stats": "Statistics",
    "options": "Options",
    "poker": "Poker Theory",
    "general": "General",
}


class KnowledgeDB:
    """Local SQLite database with migration support from the original card schema."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn, conn:
            self._create_schema(conn)
            self._seed_topics(conn)
            self._seed_code_problems(conn)
            self._seed_math_formulas(conn)
            self._relink_code_problems(conn)
            self._relink_math_formulas(conn)
            self._migrate_legacy_cards(conn)
            self._rebuild_search_index(conn)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        self._prepare_legacy_review_table(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES topics(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT,
                identifier TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source_id, chunk_index)
            );

            CREATE TABLE IF NOT EXISTS concepts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                topic_id INTEGER NOT NULL REFERENCES topics(id),
                source_id INTEGER REFERENCES sources(id),
                mastery REAL NOT NULL DEFAULT 0.0,
                leech INTEGER NOT NULL DEFAULT 0,
                ease REAL NOT NULL DEFAULT 2.5,
                interval INTEGER NOT NULL DEFAULT 0,
                repetitions INTEGER NOT NULL DEFAULT 0,
                due TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS concept_chunks (
                concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                chunk_id INTEGER NOT NULL REFERENCES content_chunks(id) ON DELETE CASCADE,
                PRIMARY KEY (concept_id, chunk_id)
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                source_id INTEGER REFERENCES sources(id),
                chunk_id INTEGER REFERENCES content_chunks(id),
                question_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '[]',
                answer_json TEXT NOT NULL DEFAULT '{}',
                explanation TEXT NOT NULL DEFAULT '',
                bloom TEXT NOT NULL DEFAULT 'apply',
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_asked TEXT,
                ask_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                UNIQUE(concept_id, fingerprint)
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                question_id INTEGER REFERENCES questions(id) ON DELETE SET NULL,
                legacy_card_id INTEGER,
                ts TEXT NOT NULL,
                correct INTEGER NOT NULL,
                confidence INTEGER NOT NULL,
                quality INTEGER NOT NULL,
                latency_seconds REAL,
                answer_text TEXT,
                critique TEXT,
                provider TEXT
            );

            CREATE TABLE IF NOT EXISTS coaching_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                provider TEXT NOT NULL,
                report TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS embeddings (
                kind TEXT NOT NULL,
                ref_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                vector BLOB NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (kind, ref_id)
            );

            -- Background work. Every provider call is a job so the UI never
            -- blocks on an LLM; ingestion runs while the learner studies.
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0.0,
                detail TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Named misconceptions are first-class: they are re-tested until
            -- resolved rather than being shown once and forgotten.
            CREATE TABLE IF NOT EXISTS misconceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                statement TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                times_seen INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                resolved_at TEXT,
                UNIQUE (concept_id, fingerprint)
            );

            CREATE TABLE IF NOT EXISTS code_problems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                starter TEXT NOT NULL,
                tests TEXT NOT NULL,
                difficulty TEXT NOT NULL DEFAULT 'medium',
                tags_json TEXT NOT NULL DEFAULT '[]',
                concept_hints_json TEXT NOT NULL DEFAULT '[]',
                concept_id INTEGER REFERENCES concepts(id) ON DELETE SET NULL,
                timeout_seconds INTEGER NOT NULL DEFAULT 8,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS code_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id INTEGER NOT NULL REFERENCES code_problems(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                passed INTEGER NOT NULL,
                passed_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                runtime_ms INTEGER,
                code TEXT NOT NULL,
                output TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS math_formulas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                latex TEXT NOT NULL,
                spoken TEXT NOT NULL,
                intuition TEXT NOT NULL DEFAULT '',
                key_phrases_json TEXT NOT NULL DEFAULT '[]',
                blanks_json TEXT NOT NULL DEFAULT '[]',
                terms_json TEXT NOT NULL DEFAULT '[]',
                tags_json TEXT NOT NULL DEFAULT '[]',
                concept_hints_json TEXT NOT NULL DEFAULT '[]',
                concept_id INTEGER REFERENCES concepts(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS math_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                formula_id INTEGER NOT NULL REFERENCES math_formulas(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                mode TEXT NOT NULL,
                passed INTEGER NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_concepts_due ON concepts(due);
            CREATE INDEX IF NOT EXISTS idx_questions_concept ON questions(concept_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_concept_ts ON reviews(concept_id, ts);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_misconceptions_concept
                ON misconceptions(concept_id, resolved_at);
            CREATE INDEX IF NOT EXISTS idx_code_attempts_problem
                ON code_attempts(problem_id, ts);
            CREATE INDEX IF NOT EXISTS idx_math_attempts_formula
                ON math_attempts(formula_id, ts);
            """
        )
        self._add_missing_columns(conn)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(kind, ref_id UNINDEXED, title, body)"
            )
        except sqlite3.OperationalError:
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('fts_available', '0')")
        else:
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('fts_available', '1')")

    def _add_missing_columns(self, conn: sqlite3.Connection) -> None:
        """Additive migrations for databases created by an earlier version.

        Kept separate from ``CREATE TABLE`` so an existing ``ultralearn.db`` picks
        up new columns without a rebuild or any data loss.
        """

        additions = {
            "reviews": {
                # How the concept was surfaced: due review, free practice, or a
                # targeted drill. Previously only implied by a call argument.
                "mode": "TEXT NOT NULL DEFAULT 'due'",
                # The examiner's 0-5 rubric score for written answers.
                "score": "INTEGER",
                "graded_by": "TEXT NOT NULL DEFAULT 'self'",
                # Denormalised so per-format analytics do not need the question
                # row, which may be retired or deleted later.
                "question_type": "TEXT NOT NULL DEFAULT ''",
                "bloom": "TEXT NOT NULL DEFAULT ''",
            },
            "questions": {
                "difficulty": "REAL NOT NULL DEFAULT 0.5",
            },
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if not existing:
                continue
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _prepare_legacy_review_table(self, conn: sqlite3.Connection) -> None:
        """Move the original card-level review table out of the way if present."""

        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'").fetchone()
        if not row:
            return
        columns = conn.execute("PRAGMA table_info(reviews)").fetchall()
        column_names = {column["name"] for column in columns}
        if "concept_id" in column_names:
            return
        legacy_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_reviews'"
        ).fetchone()
        if legacy_row:
            conn.execute("DROP TABLE reviews")
        else:
            conn.execute("ALTER TABLE reviews RENAME TO legacy_reviews")

    def _seed_topics(self, conn: sqlite3.Connection) -> None:
        now = utc_now()
        for slug, name in DEFAULT_TOPICS.items():
            conn.execute(
                "INSERT OR IGNORE INTO topics (slug, name, created_at) VALUES (?, ?, ?)",
                (slug, name, now),
            )

    def _seed_code_problems(self, conn: sqlite3.Connection) -> None:
        from .code_bank import PROBLEMS

        now = utc_now()
        for problem in PROBLEMS:
            conn.execute(
                """
                INSERT INTO code_problems (
                    slug, title, prompt, starter, tests, difficulty, tags_json,
                    concept_hints_json, timeout_seconds, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    prompt=excluded.prompt,
                    starter=excluded.starter,
                    tests=excluded.tests,
                    difficulty=excluded.difficulty,
                    tags_json=excluded.tags_json,
                    concept_hints_json=excluded.concept_hints_json
                """,
                (
                    problem["slug"],
                    problem["title"],
                    problem["prompt"],
                    problem["starter"],
                    problem["tests"],
                    problem["difficulty"],
                    json.dumps(problem.get("tags", [])),
                    json.dumps(problem.get("concept_hints", [])),
                    int(problem.get("timeout_seconds", 8)),
                    now,
                ),
            )

    def _relink_code_problems(self, conn: sqlite3.Connection) -> None:
        """Attach unlinked drills to a matching library concept when one exists."""

        concepts = conn.execute("SELECT id, title FROM concepts").fetchall()
        if not concepts:
            return
        for row in conn.execute(
            "SELECT id, concept_id, concept_hints_json FROM code_problems"
        ):
            if row["concept_id"]:
                continue
            hints = json.loads(row["concept_hints_json"] or "[]")
            match_id = _match_concept_id(concepts, hints)
            if match_id is not None:
                conn.execute(
                    "UPDATE code_problems SET concept_id=? WHERE id=?",
                    (match_id, row["id"]),
                )

    def _seed_math_formulas(self, conn: sqlite3.Connection) -> None:
        from .math_bank import FORMULAS

        now = utc_now()
        for formula in FORMULAS:
            conn.execute(
                """
                INSERT INTO math_formulas (
                    slug, title, latex, spoken, intuition, key_phrases_json,
                    blanks_json, terms_json, tags_json, concept_hints_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    latex=excluded.latex,
                    spoken=excluded.spoken,
                    intuition=excluded.intuition,
                    key_phrases_json=excluded.key_phrases_json,
                    blanks_json=excluded.blanks_json,
                    terms_json=excluded.terms_json,
                    tags_json=excluded.tags_json,
                    concept_hints_json=excluded.concept_hints_json
                """,
                (
                    formula["slug"],
                    formula["title"],
                    formula["latex"],
                    formula["spoken"],
                    formula.get("intuition", ""),
                    json.dumps(formula.get("key_phrases", [])),
                    json.dumps(formula.get("blanks", [])),
                    json.dumps(formula.get("terms", [])),
                    json.dumps(formula.get("tags", [])),
                    json.dumps(formula.get("concept_hints", [])),
                    now,
                ),
            )

    def _relink_math_formulas(self, conn: sqlite3.Connection) -> None:
        concepts = conn.execute("SELECT id, title FROM concepts").fetchall()
        if not concepts:
            return
        for row in conn.execute("SELECT id, concept_id, concept_hints_json FROM math_formulas"):
            if row["concept_id"]:
                continue
            hints = json.loads(row["concept_hints_json"] or "[]")
            match_id = _match_concept_id(concepts, hints)
            if match_id is not None:
                conn.execute(
                    "UPDATE math_formulas SET concept_id=? WHERE id=?",
                    (match_id, row["id"]),
                )

    def _migrate_legacy_cards(self, conn: sqlite3.Connection) -> None:
        if self._meta(conn, "legacy_cards_migrated") == "1":
            return
        has_cards = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cards'"
        ).fetchone()
        if not has_cards:
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('legacy_cards_migrated', '1')")
            return

        old_cards = conn.execute("SELECT * FROM cards ORDER BY id").fetchall()
        if not old_cards:
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('legacy_cards_migrated', '1')")
            return

        legacy_source_id = self.add_source(
            "legacy",
            "Legacy card import",
            tags=["legacy"],
            metadata={"from": "cards"},
            conn=conn,
        )
        card_to_concept: dict[int, int] = {}
        card_to_question: dict[int, int] = {}

        for card in old_cards:
            topic_slug = slugify(card["tag"] or "general")
            self.ensure_topic(topic_slug, card["tag"] or topic_slug, conn=conn)
            source_id = legacy_source_id
            if card["source"]:
                source_id = self.add_source(
                    "legacy",
                    card["source"],
                    tags=[topic_slug],
                    metadata={"from": "card_source"},
                    conn=conn,
                )
            title = infer_concept_title(card["question"])
            concept_id = self.find_or_create_concept(
                title=title,
                summary=card["explanation"] or "",
                topic_slug=topic_slug,
                source_id=source_id,
                due=card["due"],
                ease=float(card["ease"]),
                interval=int(card["interval"]),
                repetitions=int(card["repetitions"]),
                conn=conn,
            )
            card_to_concept[int(card["id"])] = concept_id
            answer = {"index": int(card["answer_index"])}
            question_id = self.add_question(
                concept_id=concept_id,
                source_id=source_id,
                chunk_id=None,
                question_type="single_mcq",
                prompt=card["question"],
                options=json.loads(card["options"]),
                answer=answer,
                explanation=card["explanation"] or "",
                bloom=card["bloom"] or "apply",
                conn=conn,
                allow_duplicate=True,
            )
            if question_id is not None:
                card_to_question[int(card["id"])] = question_id

        has_old_reviews = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_reviews'"
        ).fetchone()
        if has_old_reviews and self._old_reviews_have_card_id(conn, "legacy_reviews"):
            old_reviews = conn.execute("SELECT * FROM legacy_reviews ORDER BY id").fetchall()
            for review in old_reviews:
                legacy_card_id = int(review["card_id"])
                concept_id = card_to_concept.get(legacy_card_id)
                if concept_id is None:
                    continue
                conn.execute(
                    """INSERT INTO reviews
                       (concept_id, question_id, legacy_card_id, ts, correct, confidence, quality, provider)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        concept_id,
                        card_to_question.get(legacy_card_id),
                        legacy_card_id,
                        review["ts"],
                        int(review["correct"]),
                        int(review["confidence"]),
                        int(review["quality"]),
                        "legacy",
                    ),
                )

        conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('legacy_cards_migrated', '1')")

    def _old_reviews_have_card_id(self, conn: sqlite3.Connection, table: str) -> bool:
        columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(column["name"] == "card_id" for column in columns)

    def _meta(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def ensure_topic(self, slug: str, name: str | None = None, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with closing(self.connect()) as owned, owned:
                return self.ensure_topic(slug, name, owned)
        slug = slugify(slug or "general")
        conn.execute(
            "INSERT OR IGNORE INTO topics (slug, name, created_at) VALUES (?, ?, ?)",
            (slug, name or slug.replace("-", " ").title(), utc_now()),
        )
        row = conn.execute("SELECT id FROM topics WHERE slug=?", (slug,)).fetchone()
        return int(row["id"])

    def list_topics(self) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return conn.execute("SELECT * FROM topics ORDER BY slug").fetchall()

    def add_source(
        self,
        source_type: str,
        title: str,
        author: str = "",
        identifier: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if conn is None:
            with closing(self.connect()) as owned, owned:
                source_id = self.add_source(source_type, title, author, identifier, tags, metadata, owned)
                self._rebuild_search_index(owned)
                return source_id

        title = title.strip() or "Untitled source"
        row = conn.execute(
            "SELECT id FROM sources WHERE type=? AND title=? AND COALESCE(author,'')=? AND COALESCE(identifier,'')=?",
            (source_type, title, author, identifier),
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = conn.execute(
            """INSERT INTO sources
               (type, title, author, identifier, tags_json, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source_type,
                title,
                author,
                identifier,
                json.dumps(tags or []),
                json.dumps(metadata or {}),
                utc_now(),
            ),
        )
        return int(cursor.lastrowid)

    def add_content(self, source_id: int, text: str, conn: sqlite3.Connection | None = None) -> list[int]:
        if conn is None:
            with closing(self.connect()) as owned, owned:
                chunk_ids = self.add_content(source_id, text, owned)
                self._rebuild_search_index(owned)
                return chunk_ids
        chunk_ids: list[int] = []
        for index, chunk in enumerate(chunk_text(text)):
            cursor = conn.execute(
                """INSERT OR IGNORE INTO content_chunks (source_id, chunk_index, text, created_at)
                   VALUES (?, ?, ?, ?)""",
                (source_id, index, chunk, utc_now()),
            )
            if cursor.lastrowid:
                chunk_ids.append(int(cursor.lastrowid))
            else:
                row = conn.execute(
                    "SELECT id FROM content_chunks WHERE source_id=? AND chunk_index=?",
                    (source_id, index),
                ).fetchone()
                chunk_ids.append(int(row["id"]))
        return chunk_ids

    def find_or_create_concept(
        self,
        title: str,
        summary: str,
        topic_slug: str,
        source_id: int | None = None,
        chunk_id: int | None = None,
        due: str | None = None,
        ease: float = 2.5,
        interval: int = 0,
        repetitions: int = 0,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if conn is None:
            with closing(self.connect()) as owned, owned:
                concept_id = self.find_or_create_concept(
                    title, summary, topic_slug, source_id, chunk_id, due, ease, interval, repetitions, owned
                )
                self._rebuild_search_index(owned)
                return concept_id
        topic_id = self.ensure_topic(topic_slug, conn=conn)
        clean_title = clean_label(title or "Untitled concept")
        concept_key = f"{slugify(topic_slug)}:{normalize_text(clean_title)}"
        now = utc_now()
        row = conn.execute("SELECT id, summary FROM concepts WHERE concept_key=?", (concept_key,)).fetchone()
        if row:
            concept_id = int(row["id"])
            if summary and not row["summary"]:
                conn.execute(
                    "UPDATE concepts SET summary=?, updated_at=? WHERE id=?",
                    (summary, now, concept_id),
                )
        else:
            cursor = conn.execute(
                """INSERT INTO concepts
                   (concept_key, title, summary, topic_id, source_id, due, ease, interval, repetitions, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    concept_key,
                    clean_title,
                    summary or "",
                    topic_id,
                    source_id,
                    due or date.today().isoformat(),
                    ease,
                    interval,
                    repetitions,
                    now,
                    now,
                ),
            )
            concept_id = int(cursor.lastrowid)
        if chunk_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO concept_chunks (concept_id, chunk_id) VALUES (?, ?)",
                (concept_id, chunk_id),
            )
        return concept_id

    def add_provider_question(
        self,
        provider_question: ProviderQuestion,
        source_id: int | None = None,
        chunk_id: int | None = None,
        allow_duplicate: bool = False,
    ) -> int | None:
        with closing(self.connect()) as conn, conn:
            concept_id = self.find_or_create_concept(
                provider_question.concept_title,
                provider_question.concept_summary,
                provider_question.topic_slug,
                source_id,
                chunk_id,
                conn=conn,
            )
            question_id = self.add_question(
                concept_id=concept_id,
                source_id=source_id,
                chunk_id=chunk_id,
                question_type=provider_question.question_type,
                prompt=provider_question.prompt,
                options=provider_question.options,
                answer=provider_question.answer,
                explanation=provider_question.explanation,
                bloom=provider_question.bloom,
                conn=conn,
                allow_duplicate=allow_duplicate,
            )
            self._rebuild_search_index(conn)
            return question_id

    def add_question(
        self,
        concept_id: int,
        source_id: int | None,
        chunk_id: int | None,
        question_type: str,
        prompt: str,
        options: list[str],
        answer: dict[str, Any],
        explanation: str,
        bloom: str,
        conn: sqlite3.Connection | None = None,
        allow_duplicate: bool = False,
    ) -> int | None:
        if conn is None:
            with closing(self.connect()) as owned, owned:
                question_id = self.add_question(
                    concept_id,
                    source_id,
                    chunk_id,
                    question_type,
                    prompt,
                    options,
                    answer,
                    explanation,
                    bloom,
                    owned,
                    allow_duplicate,
                )
                self._rebuild_search_index(owned)
                return question_id

        existing = [
            row["prompt"]
            for row in conn.execute(
                "SELECT prompt FROM questions WHERE concept_id=? AND status='active'",
                (concept_id,),
            ).fetchall()
        ]
        if not allow_duplicate and QuestionDeduper(existing).is_duplicate(prompt):
            return None

        try:
            cursor = conn.execute(
                """INSERT INTO questions
                   (concept_id, source_id, chunk_id, question_type, prompt, options_json, answer_json,
                    explanation, bloom, fingerprint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    concept_id,
                    source_id,
                    chunk_id,
                    question_type,
                    prompt.strip(),
                    json.dumps(options or []),
                    json.dumps(answer or {}),
                    explanation or "",
                    bloom or "apply",
                    fingerprint(prompt),
                    utc_now(),
                ),
            )
        except sqlite3.IntegrityError:
            return None
        return int(cursor.lastrowid)

    def get_due_concepts(self, limit: int = 30, include_new: bool = True) -> list[Concept]:
        today = date.today().isoformat()
        new_clause = " OR c.repetitions = 0" if include_new else ""
        with closing(self.connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT c.*, t.slug AS topic_slug
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                WHERE c.due <= ?{new_clause}
                ORDER BY c.leech DESC, c.due ASC, c.mastery ASC
                LIMIT ?
                """,
                (today, limit),
            ).fetchall()
        return [concept_from_row(row) for row in rows]

    def get_practice_concepts(self, limit: int = 10, exclude_ids: Iterable[int] | None = None) -> list[Concept]:
        """Concepts for extra practice beyond what is due, weakest and soonest-due first."""

        excluded = set(exclude_ids or [])
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT c.*, t.slug AS topic_slug
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                ORDER BY c.leech DESC, c.mastery ASC, c.due ASC
                LIMIT ?
                """,
                (limit + len(excluded),),
            ).fetchall()
        concepts = [concept_from_row(row) for row in rows if int(row["id"]) not in excluded]
        return concepts[:limit]

    def get_concept(self, concept_id: int) -> Concept | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT c.*, t.slug AS topic_slug
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                WHERE c.id=?
                """,
                (concept_id,),
            ).fetchone()
        return concept_from_row(row) if row else None

    def get_question_for_concept(self, concept_id: int) -> Question | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM questions
                WHERE concept_id=? AND status='active'
                ORDER BY ask_count ASC, COALESCE(last_asked, '') ASC, created_at ASC
                LIMIT 1
                """,
                (concept_id,),
            ).fetchone()
        return question_from_row(row) if row else None

    def get_question(self, question_id: int) -> Question | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        return question_from_row(row) if row else None

    def list_concepts(self, limit: int = 500) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return conn.execute(
                """
                SELECT c.*, t.slug AS topic_slug,
                    (SELECT COUNT(*) FROM questions q
                     WHERE q.concept_id = c.id AND q.status = 'active') AS question_count,
                    (SELECT COUNT(*) FROM code_problems p
                     WHERE p.concept_id = c.id) AS code_count,
                    (SELECT COUNT(*) FROM math_formulas m
                     WHERE m.concept_id = c.id) AS math_count
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                ORDER BY t.slug, c.title
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def list_sources(self, limit: int = 200) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return conn.execute(
                """
                SELECT s.*, COUNT(ch.id) AS chunk_count
                FROM sources s
                LEFT JOIN content_chunks ch ON ch.source_id = s.id
                GROUP BY s.id
                ORDER BY s.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def list_code_problems(self, concept_id: int | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT p.id, p.slug, p.title, p.prompt, p.starter, p.difficulty,
                   p.tags_json, p.concept_id, p.timeout_seconds,
                   c.title AS concept_title,
                   (SELECT COUNT(*) FROM code_attempts a WHERE a.problem_id = p.id) AS attempts,
                   (SELECT MAX(a.passed) FROM code_attempts a WHERE a.problem_id = p.id) AS ever_passed,
                   (SELECT a.passed FROM code_attempts a WHERE a.problem_id = p.id
                    ORDER BY a.ts DESC LIMIT 1) AS last_passed,
                   (SELECT a.code FROM code_attempts a WHERE a.problem_id = p.id
                    ORDER BY a.ts DESC LIMIT 1) AS last_code
            FROM code_problems p
            LEFT JOIN concepts c ON c.id = p.concept_id
        """
        params: list[Any] = []
        if concept_id is not None:
            query += " WHERE p.concept_id = ?"
            params.append(concept_id)
        query += " ORDER BY CASE p.difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, p.title"
        with closing(self.connect()) as conn:
            return conn.execute(query, params).fetchall()

    def get_code_problem(self, problem_id: int, *, include_tests: bool = False) -> sqlite3.Row | None:
        columns = "p.*, c.title AS concept_title" if include_tests else (
            "p.id, p.slug, p.title, p.prompt, p.starter, p.difficulty, p.tags_json, "
            "p.concept_id, p.timeout_seconds, c.title AS concept_title"
        )
        with closing(self.connect()) as conn:
            return conn.execute(
                f"""
                SELECT {columns}
                FROM code_problems p
                LEFT JOIN concepts c ON c.id = p.concept_id
                WHERE p.id = ?
                """,
                (problem_id,),
            ).fetchone()

    def record_code_attempt(
        self,
        problem_id: int,
        code: str,
        passed: bool,
        passed_count: int,
        failed_count: int,
        runtime_ms: int,
        output: str,
    ) -> int:
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO code_attempts (
                    problem_id, ts, passed, passed_count, failed_count, runtime_ms, code, output
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    problem_id,
                    utc_now(),
                    int(passed),
                    passed_count,
                    failed_count,
                    runtime_ms,
                    code,
                    output[:4000],
                ),
            )
            return int(cursor.lastrowid)

    def due_code_problem_count(self) -> int:
        """Drills linked to a concept that is due today."""

        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM code_problems p
                JOIN concepts c ON c.id = p.concept_id
                WHERE c.due <= ?
                """,
                (date.today().isoformat(),),
            ).fetchone()
        return int(row["n"] or 0)

    def list_math_formulas(self, concept_id: int | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT f.id, f.slug, f.title, f.latex, f.intuition, f.tags_json,
                   f.concept_id, f.blanks_json, f.terms_json,
                   c.title AS concept_title,
                   (SELECT COUNT(*) FROM math_attempts a WHERE a.formula_id = f.id) AS attempts,
                   (SELECT MAX(a.passed) FROM math_attempts a WHERE a.formula_id = f.id) AS ever_passed
            FROM math_formulas f
            LEFT JOIN concepts c ON c.id = f.concept_id
        """
        params: list[Any] = []
        if concept_id is not None:
            query += " WHERE f.concept_id = ?"
            params.append(concept_id)
        query += " ORDER BY f.title"
        with closing(self.connect()) as conn:
            return conn.execute(query, params).fetchall()

    def get_math_formula(self, formula_id: int, *, include_answers: bool = False) -> sqlite3.Row | None:
        columns = "f.*, c.title AS concept_title" if include_answers else (
            "f.id, f.slug, f.title, f.latex, f.intuition, f.tags_json, f.concept_id, "
            "f.blanks_json, f.terms_json, c.title AS concept_title"
        )
        with closing(self.connect()) as conn:
            return conn.execute(
                f"""
                SELECT {columns}
                FROM math_formulas f
                LEFT JOIN concepts c ON c.id = f.concept_id
                WHERE f.id = ?
                """,
                (formula_id,),
            ).fetchone()

    def add_math_formula(
        self,
        slug: str,
        title: str,
        latex: str,
        spoken: str,
        intuition: str = "",
        key_phrases: list[str] | None = None,
        blanks: list[dict[str, Any]] | None = None,
        terms: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        concept_id: int | None = None,
        concept_hints: list[str] | None = None,
    ) -> int:
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO math_formulas (
                    slug, title, latex, spoken, intuition, key_phrases_json,
                    blanks_json, terms_json, tags_json, concept_hints_json,
                    concept_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    latex=excluded.latex,
                    spoken=excluded.spoken,
                    intuition=excluded.intuition,
                    key_phrases_json=excluded.key_phrases_json,
                    blanks_json=excluded.blanks_json,
                    terms_json=excluded.terms_json,
                    tags_json=excluded.tags_json,
                    concept_id=COALESCE(excluded.concept_id, math_formulas.concept_id)
                """,
                (
                    slug,
                    title,
                    latex,
                    spoken,
                    intuition,
                    json.dumps(key_phrases or []),
                    json.dumps(blanks or []),
                    json.dumps(terms or []),
                    json.dumps(tags or []),
                    json.dumps(concept_hints or []),
                    concept_id,
                    now,
                ),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute("SELECT id FROM math_formulas WHERE slug=?", (slug,)).fetchone()
            return int(row["id"])

    def record_math_attempt(
        self,
        formula_id: int,
        mode: str,
        passed: bool,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> int:
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO math_attempts (formula_id, ts, mode, passed, payload_json, result_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (formula_id, utc_now(), mode, int(passed), json.dumps(payload), json.dumps(result)),
            )
            return int(cursor.lastrowid)

    def due_math_formula_count(self) -> int:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM math_formulas f
                JOIN concepts c ON c.id = f.concept_id
                WHERE c.due <= ?
                """,
                (date.today().isoformat(),),
            ).fetchone()
        return int(row["n"] or 0)

    # ------------------------------------------------------------------
    # Semantic retrieval (local vector index over chunks and concepts)
    # ------------------------------------------------------------------

    def ensure_embeddings(self) -> None:
        """Embed any chunks/concepts that are missing vectors for the active embedder.

        Runs lazily before retrieval so newly ingested content is always indexed,
        and re-indexes everything automatically if the embedder model changes.
        """

        embedder = get_embedder()
        with closing(self.connect()) as conn, conn:
            chunk_rows = conn.execute(
                """
                SELECT ch.id, ch.text FROM content_chunks ch
                LEFT JOIN embeddings e ON e.kind='chunk' AND e.ref_id=ch.id AND e.model=?
                WHERE e.ref_id IS NULL
                """,
                (embedder.name,),
            ).fetchall()
            concept_rows = conn.execute(
                """
                SELECT c.id, c.title, c.summary FROM concepts c
                LEFT JOIN embeddings e ON e.kind='concept' AND e.ref_id=c.id AND e.model=?
                WHERE e.ref_id IS NULL
                """,
                (embedder.name,),
            ).fetchall()
            now = utc_now()
            if chunk_rows:
                vectors = embedder.embed([row["text"] for row in chunk_rows])
                for row, vector in zip(chunk_rows, vectors):
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings (kind, ref_id, model, vector, created_at) VALUES ('chunk', ?, ?, ?, ?)",
                        (row["id"], embedder.name, pack_vector(vector), now),
                    )
            if concept_rows:
                vectors = embedder.embed([f"{row['title']}. {row['summary']}" for row in concept_rows])
                for row, vector in zip(concept_rows, vectors):
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings (kind, ref_id, model, vector, created_at) VALUES ('concept', ?, ?, ?, ?)",
                        (row["id"], embedder.name, pack_vector(vector), now),
                    )

    def semantic_chunks(self, query: str, k: int = 6) -> list[dict[str, Any]]:
        """Chunks most similar to the query, across every source, with metadata."""

        self.ensure_embeddings()
        embedder = get_embedder()
        query_vector = embedder.embed([query])[0]
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT ch.id, ch.text, ch.source_id, s.title AS source_title, s.type AS source_type,
                       e.vector
                FROM content_chunks ch
                JOIN sources s ON s.id = ch.source_id
                JOIN embeddings e ON e.kind='chunk' AND e.ref_id=ch.id AND e.model=?
                """,
                (embedder.name,),
            ).fetchall()
        scored = [
            {
                "chunk_id": int(row["id"]),
                "source_id": int(row["source_id"]),
                "source_title": row["source_title"],
                "source_type": row["source_type"],
                "text": row["text"],
                "score": cosine(query_vector, unpack_vector(row["vector"])),
            }
            for row in rows
        ]
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]

    def semantic_concepts(self, query: str, k: int = 10) -> list[tuple[Concept, float]]:
        """Concepts most similar to the query, for building focused quiz rounds."""

        self.ensure_embeddings()
        embedder = get_embedder()
        query_vector = embedder.embed([query])[0]
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT c.*, t.slug AS topic_slug, e.vector
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                JOIN embeddings e ON e.kind='concept' AND e.ref_id=c.id AND e.model=?
                """,
                (embedder.name,),
            ).fetchall()
        scored = [
            (concept_from_row(row), cosine(query_vector, unpack_vector(row["vector"])))
            for row in rows
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def best_chunk_for_text(self, source_id: int, text: str) -> int | None:
        """The chunk of a source most similar to the text (for concept-chunk linking)."""

        self.ensure_embeddings()
        embedder = get_embedder()
        query_vector = embedder.embed([text])[0]
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT ch.id, e.vector
                FROM content_chunks ch
                JOIN embeddings e ON e.kind='chunk' AND e.ref_id=ch.id AND e.model=?
                WHERE ch.source_id=?
                """,
                (embedder.name, source_id),
            ).fetchall()
        if not rows:
            return None
        best = max(rows, key=lambda row: cosine(query_vector, unpack_vector(row["vector"])))
        return int(best["id"])

    def source_text(self, source_id: int, limit_chars: int = 14000) -> str:
        """Concatenated chunk text for a saved source, for regeneration."""

        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT text FROM content_chunks WHERE source_id=? ORDER BY chunk_index",
                (source_id,),
            ).fetchall()
        return "\n\n".join(row["text"] for row in rows)[:limit_chars]

    def prompts_for_source(self, source_id: int) -> list[str]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT prompt FROM questions WHERE source_id=? AND status='active'",
                (source_id,),
            ).fetchall()
        return [row["prompt"] for row in rows]

    def existing_prompts_for_concept(self, concept_id: int) -> list[str]:
        with closing(self.connect()) as conn:
            return [
                row["prompt"]
                for row in conn.execute(
                    "SELECT prompt FROM questions WHERE concept_id=? AND status='active'",
                    (concept_id,),
                ).fetchall()
            ]

    def source_context_for_concept(self, concept_id: int, limit_chars: int = 6000) -> str:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT ch.text
                FROM content_chunks ch
                JOIN concept_chunks cc ON cc.chunk_id = ch.id
                WHERE cc.concept_id=?
                ORDER BY ch.chunk_index
                """,
                (concept_id,),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    """
                    SELECT c.summary AS text FROM concepts c WHERE c.id=?
                    """,
                    (concept_id,),
                ).fetchall()
        return "\n\n".join(row["text"] for row in rows if row["text"])[:limit_chars]

    def record_review(
        self,
        concept_id: int,
        question_id: int | None,
        correct: bool,
        confidence: int,
        quality: int,
        latency_seconds: float | None = None,
        answer_text: str = "",
        critique: str = "",
        provider: str = "",
        update_schedule: bool = True,
        mode: str = "due",
        score: int | None = None,
        graded_by: str = "self",
    ) -> None:
        """Log a review and update the concept.

        ``update_schedule=False`` is for practice reviews of concepts that were not
        due: the attempt still counts toward mastery and leech detection, but the
        SM-2 schedule is untouched so early extra practice cannot inflate intervals.
        """

        with closing(self.connect()) as conn, conn:
            concept = conn.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
            if concept is None:
                raise ValueError(f"Unknown concept id: {concept_id}")
            # Denormalised so per-format analytics survive a question being retired.
            question_type, bloom = "", ""
            if question_id is not None:
                question = conn.execute(
                    "SELECT question_type, bloom FROM questions WHERE id=?", (question_id,)
                ).fetchone()
                if question is not None:
                    question_type = question["question_type"]
                    bloom = question["bloom"]
            conn.execute(
                """INSERT INTO reviews
                   (concept_id, question_id, ts, correct, confidence, quality, latency_seconds,
                    answer_text, critique, provider, mode, score, graded_by, question_type, bloom)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    concept_id,
                    question_id,
                    utc_now(),
                    int(correct),
                    int(confidence),
                    int(quality),
                    latency_seconds,
                    answer_text,
                    critique,
                    provider,
                    mode,
                    score,
                    graded_by,
                    question_type,
                    bloom,
                ),
            )
            mastery = self._next_mastery(conn, concept_id)
            leech = self._is_leech(conn, concept_id)
            if update_schedule:
                state = schedule_review_state(
                    float(concept["ease"]),
                    int(concept["interval"]),
                    int(concept["repetitions"]),
                    quality,
                )
                conn.execute(
                    """UPDATE concepts
                       SET ease=?, interval=?, repetitions=?, due=?, mastery=?, leech=?, updated_at=?
                       WHERE id=?""",
                    (
                        state.ease,
                        state.interval,
                        state.repetitions,
                        state.due,
                        mastery,
                        int(leech),
                        utc_now(),
                        concept_id,
                    ),
                )
            elif quality < 3:
                # A practice miss reveals fragility: pull the concept back into the
                # due queue immediately without touching ease/interval.
                conn.execute(
                    "UPDATE concepts SET mastery=?, leech=?, due=?, updated_at=? WHERE id=?",
                    (mastery, int(leech), date.today().isoformat(), utc_now(), concept_id),
                )
            else:
                conn.execute(
                    "UPDATE concepts SET mastery=?, leech=?, updated_at=? WHERE id=?",
                    (mastery, int(leech), utc_now(), concept_id),
                )
            if question_id is not None:
                conn.execute(
                    "UPDATE questions SET ask_count=ask_count+1, last_asked=? WHERE id=?",
                    (utc_now(), question_id),
                )

    def _next_mastery(self, conn: sqlite3.Connection, concept_id: int) -> float:
        rows = conn.execute(
            "SELECT correct, quality, confidence FROM reviews WHERE concept_id=? ORDER BY ts DESC LIMIT 12",
            (concept_id,),
        ).fetchall()
        if not rows:
            return 0.0
        weighted = 0.0
        total_weight = 0.0
        for index, row in enumerate(rows):
            weight = 1.0 / (index + 1)
            quality_score = max(0.0, min(1.0, float(row["quality"]) / 5.0))
            correct_score = 1.0 if row["correct"] else 0.0
            weighted += weight * (0.65 * correct_score + 0.35 * quality_score)
            total_weight += weight
        return round(weighted / total_weight, 3)

    def _is_leech(self, conn: sqlite3.Connection, concept_id: int) -> bool:
        rows = conn.execute(
            "SELECT correct, confidence FROM reviews WHERE concept_id=? ORDER BY ts DESC LIMIT 8",
            (concept_id,),
        ).fetchall()
        if len(rows) < 4:
            return False
        misses = sum(1 for row in rows if not row["correct"])
        confident_misses = sum(1 for row in rows if not row["correct"] and row["confidence"] >= 4)
        return misses >= 3 or confident_misses >= 2

    def stats(self) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            concept_count = conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"]
            question_count = conn.execute("SELECT COUNT(*) AS n FROM questions WHERE status='active'").fetchone()["n"]
            source_count = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
            review_count = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
            due_count = conn.execute(
                "SELECT COUNT(*) AS n FROM concepts WHERE due <= ?",
                (date.today().isoformat(),),
            ).fetchone()["n"]
            leech_count = conn.execute("SELECT COUNT(*) AS n FROM concepts WHERE leech=1").fetchone()["n"]
            try:
                code_count = conn.execute("SELECT COUNT(*) AS n FROM code_problems").fetchone()["n"]
            except sqlite3.OperationalError:
                code_count = 0
            try:
                math_count = conn.execute("SELECT COUNT(*) AS n FROM math_formulas").fetchone()["n"]
            except sqlite3.OperationalError:
                math_count = 0
        return {
            "concepts": concept_count,
            "questions": question_count,
            "sources": source_count,
            "reviews": review_count,
            "due": due_count,
            "leeches": leech_count,
            "code_problems": code_count,
            "math_formulas": math_count,
        }

    def topic_mastery(self) -> dict[str, float]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT t.slug, AVG(c.mastery) AS mastery
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                GROUP BY t.slug
                ORDER BY t.slug
                """
            ).fetchall()
        return {row["slug"]: float(row["mastery"] or 0.0) for row in rows}

    def calibration(self) -> dict[str, float]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT confidence, AVG(correct) AS accuracy
                FROM reviews
                GROUP BY confidence
                ORDER BY confidence
                """
            ).fetchall()
        return {str(int(row["confidence"])): float(row["accuracy"]) for row in rows}

    def weak_spots(self, limit: int = 10) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return conn.execute(
                """
                SELECT c.id, c.title, t.slug AS topic_slug, c.mastery, c.leech,
                       COUNT(r.id) AS reviews,
                       AVG(r.correct) AS accuracy,
                       SUM(CASE WHEN r.correct=0 AND r.confidence>=4 THEN 1 ELSE 0 END) AS overconfident_misses
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                LEFT JOIN reviews r ON r.concept_id = c.id
                GROUP BY c.id
                HAVING reviews > 0 AND (c.leech = 1 OR c.mastery < 0.75 OR accuracy < 0.7)
                ORDER BY c.leech DESC, accuracy ASC, overconfident_misses DESC, c.mastery ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def coaching_context(self) -> str:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT c.title, t.slug AS topic, c.mastery, c.leech,
                       COUNT(r.id) AS reviews,
                       AVG(r.correct) AS accuracy,
                       AVG(r.confidence) AS avg_confidence,
                       SUM(CASE WHEN r.correct=0 AND r.confidence>=4 THEN 1 ELSE 0 END) AS overconfident_misses
                FROM concepts c
                JOIN topics t ON t.id = c.topic_id
                LEFT JOIN reviews r ON r.concept_id = c.id
                GROUP BY c.id
                ORDER BY c.leech DESC, c.mastery ASC, reviews DESC
                LIMIT 80
                """
            ).fetchall()
        lines = []
        for row in rows:
            lines.append(
                f"{row['topic']} | {row['title']} | mastery={row['mastery']:.2f} "
                f"| leech={bool(row['leech'])} | reviews={row['reviews']} "
                f"| accuracy={row['accuracy'] if row['accuracy'] is not None else 'n/a'} "
                f"| avg_confidence={row['avg_confidence'] if row['avg_confidence'] is not None else 'n/a'} "
                f"| overconfident_misses={row['overconfident_misses'] or 0}"
            )
        return "\n".join(lines)

    def save_coaching_report(self, provider: str, report: str) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "INSERT INTO coaching_reports (ts, provider, report) VALUES (?, ?, ?)",
                (utc_now(), provider, report),
            )

    def recent_coaching_reports(self, limit: int = 5) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return conn.execute(
                "SELECT * FROM coaching_reports ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def daily_activity(self, days: int = 30) -> list[dict[str, Any]]:
        """Reviews per day, most recent last, with empty days filled in."""

        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT date(ts) AS day, COUNT(*) AS reviews,
                       SUM(correct) AS correct
                FROM reviews
                WHERE date(ts) >= date('now', ?)
                GROUP BY day
                """,
                (f"-{max(1, days) - 1} days",),
            ).fetchall()
        counts = {row["day"]: row for row in rows}
        today = date.today()
        out: list[dict[str, Any]] = []
        for offset in range(days - 1, -1, -1):
            day = (today - timedelta(days=offset)).isoformat()
            row = counts.get(day)
            reviews = int(row["reviews"]) if row else 0
            correct = int(row["correct"] or 0) if row else 0
            out.append(
                {
                    "date": day,
                    "reviews": reviews,
                    "accuracy": round(correct / reviews, 3) if reviews else None,
                }
            )
        return out

    def streak_days(self) -> int:
        """Consecutive days with at least one review, counting back from today.

        A streak survives until a day is actually missed, so studying today after
        studying yesterday continues it, and not having studied *yet* today does
        not break it.
        """

        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT DISTINCT date(ts) AS day FROM reviews ORDER BY day DESC LIMIT 400"
            ).fetchall()
        active = {row["day"] for row in rows}
        if not active:
            return 0
        today = date.today()
        cursor = today if today.isoformat() in active else today - timedelta(days=1)
        streak = 0
        while cursor.isoformat() in active:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    def reviewed_today(self) -> int:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM reviews WHERE date(ts) = date('now')"
            ).fetchone()
        return int(row["n"] or 0)

    # ------------------------------------------------------------------
    # Background jobs
    # ------------------------------------------------------------------

    def enqueue_job(self, kind: str, payload: dict[str, Any] | None = None, label: str = "") -> int:
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (kind, label, payload_json, status, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (kind, label, json.dumps(payload or {}), now, now),
            )
            return int(cursor.lastrowid)

    def claim_next_job(self) -> sqlite3.Row | None:
        """Atomically move the oldest queued job to running and return it."""

        with closing(self.connect()) as conn, conn:
            # IMMEDIATE takes the write lock up front, so two workers cannot both
            # see the same row as queued.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status='running', updated_at=? WHERE id=?",
                (utc_now(), row["id"]),
            )
            return row

    def update_job(
        self,
        job_id: int,
        *,
        progress: float | None = None,
        detail: str | None = None,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        assignments: list[str] = ["updated_at=?"]
        values: list[Any] = [utc_now()]
        if progress is not None:
            assignments.append("progress=?")
            values.append(max(0.0, min(1.0, progress)))
        if detail is not None:
            assignments.append("detail=?")
            values.append(detail)
        if status is not None:
            assignments.append("status=?")
            values.append(status)
        if result is not None:
            assignments.append("result_json=?")
            values.append(json.dumps(result))
        if error is not None:
            assignments.append("error=?")
            values.append(error)
        values.append(job_id)
        with closing(self.connect()) as conn, conn:
            conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id=?", values)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return job_to_dict(row) if row else None

    def list_jobs(self, limit: int = 20, active_only: bool = False) -> list[dict[str, Any]]:
        clause = "WHERE status IN ('queued', 'running')" if active_only else ""
        with closing(self.connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {clause} ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [job_to_dict(row) for row in rows]

    def requeue_stale_jobs(self) -> int:
        """Reset jobs left running by a crash so they are not stuck forever."""

        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='queued', progress=0, updated_at=? WHERE status='running'",
                (utc_now(),),
            )
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Misconceptions
    # ------------------------------------------------------------------

    def record_misconception(self, concept_id: int, statement: str) -> int | None:
        """Log a named misconception, merging repeats of the same one."""

        statement = statement.strip()
        if not statement:
            return None
        key = fingerprint(statement)
        now = utc_now()
        with closing(self.connect()) as conn, conn:
            existing = conn.execute(
                "SELECT id FROM misconceptions WHERE concept_id=? AND fingerprint=?",
                (concept_id, key),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE misconceptions
                    SET times_seen = times_seen + 1, last_seen = ?, resolved_at = NULL
                    WHERE id = ?
                    """,
                    (now, existing["id"]),
                )
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO misconceptions
                    (concept_id, statement, fingerprint, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (concept_id, statement, key, now, now),
            )
            return int(cursor.lastrowid)

    def open_misconceptions(self, concept_id: int | None = None, limit: int = 50) -> list[sqlite3.Row]:
        clause = "AND m.concept_id = ?" if concept_id is not None else ""
        params: list[Any] = [concept_id] if concept_id is not None else []
        params.append(limit)
        with closing(self.connect()) as conn:
            return conn.execute(
                f"""
                SELECT m.*, c.title AS concept_title, t.slug AS topic_slug
                FROM misconceptions m
                JOIN concepts c ON c.id = m.concept_id
                JOIN topics t ON t.id = c.topic_id
                WHERE m.resolved_at IS NULL {clause}
                ORDER BY m.times_seen DESC, m.last_seen DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

    def resolve_misconceptions(self, concept_id: int) -> int:
        """Retire a concept's open misconceptions after a clean answer."""

        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE misconceptions SET resolved_at=? WHERE concept_id=? AND resolved_at IS NULL",
                (utc_now(), concept_id),
            )
            return cursor.rowcount

    def unified_search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Keyword hits plus semantic neighbours, merged and de-duplicated.

        FTS is exact; the vector index is for the case where the learner asks
        in their own words ("why do early layers stop learning") rather than
        the phrase that happens to be in the notes.
        """

        query = query.strip()
        if not query:
            return []

        hits: dict[tuple[str, int], dict[str, Any]] = {}
        for row in self.search(query, limit=limit):
            key = (row["kind"], int(row["ref_id"]))
            hits[key] = {
                "kind": row["kind"],
                "ref_id": int(row["ref_id"]),
                "title": row["title"],
                "snippet": str(row["snippet"] or "")[:400],
                "via": "text",
                "score": None,
            }

        try:
            for chunk in self.semantic_chunks(query, k=limit):
                if chunk["score"] < _SEMANTIC_FLOOR:
                    continue
                key = ("chunk", chunk["chunk_id"])
                snippet = str(chunk["text"] or "")[:400]
                previous = hits.get(key)
                hits[key] = {
                    "kind": "chunk",
                    "ref_id": chunk["chunk_id"],
                    "title": chunk["source_title"],
                    "snippet": snippet if not previous else previous["snippet"],
                    "via": "both" if previous else "semantic",
                    "score": chunk["score"],
                }
            for concept, score in self.semantic_concepts(query, k=limit):
                if score < _SEMANTIC_FLOOR:
                    continue
                key = ("concept", concept.id)
                previous = hits.get(key)
                hits[key] = {
                    "kind": "concept",
                    "ref_id": concept.id,
                    "title": concept.title,
                    "snippet": (previous["snippet"] if previous else concept.summary)[:400],
                    "via": "both" if previous else "semantic",
                    "score": score,
                }
        except Exception:
            # A missing or empty embedding table must not take search down.
            pass

        ranked = sorted(
            hits.values(),
            key=lambda item: (
                0 if item["via"] == "both" else 1 if item["via"] == "semantic" else 2,
                -(item["score"] or 0.0),
            ),
        )
        return ranked[:limit]

    def search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        query = query.strip()
        if not query:
            return []
        with closing(self.connect()) as conn:
            if self._meta(conn, "fts_available") == "1":
                try:
                    return conn.execute(
                        """
                        SELECT kind, ref_id, title, snippet(search_fts, 3, '[', ']', '...', 12) AS snippet
                        FROM search_fts
                        WHERE search_fts MATCH ?
                        LIMIT ?
                        """,
                        (fts_query(query), limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    pass
            like = f"%{query}%"
            return conn.execute(
                """
                SELECT 'concept' AS kind, id AS ref_id, title, summary AS snippet
                FROM concepts
                WHERE title LIKE ? OR summary LIKE ?
                UNION ALL
                SELECT 'source' AS kind, id AS ref_id, title, metadata_json AS snippet
                FROM sources
                WHERE title LIKE ? OR author LIKE ? OR identifier LIKE ?
                UNION ALL
                SELECT 'chunk' AS kind, id AS ref_id, 'Source chunk ' || id AS title, text AS snippet
                FROM content_chunks
                WHERE text LIKE ?
                LIMIT ?
                """,
                (like, like, like, like, like, like, limit),
            ).fetchall()

    def _rebuild_search_index(self, conn: sqlite3.Connection) -> None:
        if self._meta(conn, "fts_available") != "1":
            return
        try:
            conn.execute("DELETE FROM search_fts")
            for row in conn.execute("SELECT id, title, summary FROM concepts"):
                conn.execute(
                    "INSERT INTO search_fts (kind, ref_id, title, body) VALUES ('concept', ?, ?, ?)",
                    (row["id"], row["title"], row["summary"]),
                )
            for row in conn.execute("SELECT id, title, author, identifier, tags_json, metadata_json FROM sources"):
                body = " ".join(
                    str(part or "")
                    for part in [row["author"], row["identifier"], row["tags_json"], row["metadata_json"]]
                )
                conn.execute(
                    "INSERT INTO search_fts (kind, ref_id, title, body) VALUES ('source', ?, ?, ?)",
                    (row["id"], row["title"], body),
                )
            for row in conn.execute("SELECT id, source_id, text FROM content_chunks"):
                conn.execute(
                    "INSERT INTO search_fts (kind, ref_id, title, body) VALUES ('chunk', ?, ?, ?)",
                    (row["id"], f"Source {row['source_id']} chunk", row["text"]),
                )
        except sqlite3.OperationalError:
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('fts_available', '0')")


def job_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Shape a job row for the API, decoding its JSON columns."""

    return {
        "id": int(row["id"]),
        "kind": row["kind"],
        "label": row["label"],
        "status": row["status"],
        "progress": float(row["progress"]),
        "detail": row["detail"],
        "result": json.loads(row["result_json"] or "{}"),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def concept_from_row(row: sqlite3.Row) -> Concept:
    return Concept(
        id=int(row["id"]),
        title=row["title"],
        summary=row["summary"],
        topic_slug=row["topic_slug"],
        mastery=float(row["mastery"]),
        leech=bool(row["leech"]),
        ease=float(row["ease"]),
        interval=int(row["interval"]),
        repetitions=int(row["repetitions"]),
        due=row["due"],
    )


def question_from_row(row: sqlite3.Row) -> Question:
    return Question(
        id=int(row["id"]),
        concept_id=int(row["concept_id"]),
        question_type=row["question_type"],
        prompt=row["prompt"],
        options=json.loads(row["options_json"]),
        answer=json.loads(row["answer_json"]),
        explanation=row["explanation"],
        bloom=row["bloom"],
        ask_count=int(row["ask_count"]),
    )


def chunk_text(text: str, max_chars: int = 2600) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = paragraph if not current else f"{current}\n\n{paragraph}"
    if current:
        chunks.append(current)
    return chunks


def slugify(value: str) -> str:
    value = normalize_text(value).replace(" ", "-")
    return value or "general"


def _match_concept_id(concepts: list[sqlite3.Row], hints: list[str]) -> int | None:
    if not hints:
        return None
    lowered = [(int(row["id"]), str(row["title"]).lower()) for row in concepts]
    for hint in hints:
        needle = hint.lower()
        for concept_id, title in lowered:
            if needle in title:
                return concept_id
    return None


def clean_label(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return value[:120] or "Untitled concept"


def infer_concept_title(question: str) -> str:
    text = re.sub(r"\s+", " ", question.strip())
    text = re.sub(r"^(which|what|why|how|when|where)\s+", "", text, flags=re.IGNORECASE)
    text = text.rstrip("?")
    if len(text) <= 80:
        return clean_label(text)
    words = text.split()
    return clean_label(" ".join(words[:10]))


# MiniLM cosine for a related passage is typically 0.3–0.6. Unrelated noise
# clusters around 0.20–0.27, especially if the query contains a generic word
# like "concept". Drop semantic-only neighbours under this so junk queries
# do not fill the results with the nearest random chunks.
_SEMANTIC_FLOOR = 0.30

_FTS_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "into", "your",
    "what", "when", "where", "which", "such", "are", "was", "not",
}


def fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    terms = [term for term in tokens if len(term) >= 3 and term.lower() not in _FTS_STOP]
    if not terms:
        terms = tokens
    return " AND ".join(terms) if terms else query


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
