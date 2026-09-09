"""Tests for the ingest pipeline and the loaders feeding it."""

import json

import pytest

from ultralearn import ingest
from ultralearn.db import KnowledgeDB
from ultralearn.jobs import JobWorker, ProgressReporter
from ultralearn.loaders import (
    UnsupportedSourceError,
    _normalize_arxiv,
    extract_file,
    html_to_text,
    iter_supported_files,
)
from ultralearn.models import ProviderQuestion
from ultralearn.providers import PromptProvider, ProviderError


@pytest.fixture
def db(tmp_path):
    database = KnowledgeDB(tmp_path / "ingest.db")
    database.initialize()
    return database


class ScriptedProvider(PromptProvider):
    """Returns a fixed concept list, then a question per concept."""

    name = "scripted"

    def __init__(self, concepts, fail_on=()):
        self.concepts = concepts
        self.fail_on = set(fail_on)
        self.generated_for: list[str] = []

    def available(self) -> bool:
        return True

    def _complete(self, prompt: str, schema=None) -> str:
        return json.dumps({"topic_slug": "dl", "concepts": self.concepts})

    def generate_questions(self, text, n, topic_slug, source_title="", concept_title="",
                           bloom_hint="", avoid_prompts=None):
        if concept_title in self.fail_on:
            raise ProviderError("model was overloaded")
        self.generated_for.append(concept_title)
        return [
            ProviderQuestion(
                # Deliberately different from the indexed concept, to prove the
                # pipeline pins questions to the concept it actually recorded.
                concept_title="something the model made up",
                concept_summary="",
                topic_slug="general",
                question_type="short_answer",
                prompt=f"Explain {concept_title} in a new situation.",
                options=[],
                answer={"text": "the mechanism"},
                explanation="",
                bloom="apply",
            )
        ]


def run_ingest(db, provider, payload):
    job_id = db.enqueue_job("ingest", payload)
    JobWorker(db, lambda: provider).run_once()
    return db.get_job(job_id)


def test_pasted_text_becomes_concepts_and_questions(db):
    provider = ScriptedProvider(
        [
            {"title": "Vanishing gradients", "summary": "Saturating activations shrink them."},
            {"title": "Batch norm at small batches", "summary": "Estimates get noisy."},
        ]
    )
    job = run_ingest(
        db, provider, {"text": "# Notes\nDeep nets and normalisation.", "generate": True}
    )

    assert job["status"] == "succeeded"
    assert job["result"]["concepts"] == 2
    assert job["result"]["questions"] == 2
    # No forms were supplied, yet the source is titled and filed.
    assert db.list_sources()[0]["title"] == "Notes"


def test_questions_are_pinned_to_the_indexed_concept(db):
    """The generator must not invent a parallel set of concept names."""

    provider = ScriptedProvider([{"title": "Vanishing gradients", "summary": "Shrink."}])
    run_ingest(db, provider, {"text": "notes", "generate": True})

    titles = [row["title"] for row in db.list_concepts()]
    assert titles == ["Vanishing gradients"]
    assert "something the model made up" not in titles


def test_one_failing_concept_does_not_sink_the_source(db):
    provider = ScriptedProvider(
        [
            {"title": "Good concept", "summary": "fine"},
            {"title": "Doomed concept", "summary": "fails"},
        ],
        fail_on={"Doomed concept"},
    )
    job = run_ingest(db, provider, {"text": "notes", "generate": True})

    assert job["status"] == "succeeded"
    assert job["result"]["questions"] == 1
    assert provider.generated_for == ["Good concept"]


def test_generation_can_be_skipped_to_just_file_the_material(db):
    provider = ScriptedProvider([{"title": "Unused", "summary": ""}])
    job = run_ingest(db, provider, {"text": "just filing this", "generate": False})

    assert job["result"]["chunks"] > 0
    assert job["result"]["questions"] == 0
    assert provider.generated_for == []


def test_empty_source_fails_the_job_with_a_readable_reason(db):
    job = run_ingest(db, ScriptedProvider([]), {"text": "   ", "generate": False})
    assert job["status"] == "failed"
    assert "no readable text" in job["error"].lower()


def test_progress_is_reported_through_the_pipeline(db):
    seen: list[tuple[float, str]] = []

    class Recorder(ProgressReporter):
        def __init__(self):
            pass

        def __call__(self, fraction, detail=""):
            seen.append((fraction, detail))

    ingest.run_ingest(
        db,
        ScriptedProvider([{"title": "A concept", "summary": "s"}]),
        {"text": "notes", "generate": True},
        Recorder(),
    )
    assert seen[0][0] < seen[-1][0]
    assert seen[-1][0] == 1.0


def test_concept_extraction_ignores_malformed_entries(db):
    provider = ScriptedProvider(
        [
            {"title": "Real concept", "summary": "yes"},
            {"summary": "no title, so unusable"},
            {"title": "Real concept", "summary": "an exact duplicate"},
        ]
    )
    _, concepts = ingest.extract_concepts(provider, "text", db)
    assert [concept["title"] for concept in concepts] == ["Real concept"]


def test_concept_extraction_is_capped(db):
    provider = ScriptedProvider(
        [{"title": f"Concept {i}", "summary": "s"} for i in range(40)]
    )
    _, concepts = ingest.extract_concepts(provider, "text", db)
    assert len(concepts) == ingest.MAX_CONCEPTS_PER_SOURCE


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def test_markdown_title_comes_from_the_heading():
    document = extract_file("notes.md", b"# Attention Is All You Need\n\nBody text.")
    assert document.title == "Attention Is All You Need"


def test_filename_is_the_fallback_title():
    document = extract_file("gpu_kernel_notes.txt", b"no heading here")
    assert document.title == "gpu kernel notes"


def test_html_extraction_drops_chrome_and_scripts():
    markup = """
      <html><head><title>Pot Odds</title><style>body{color:red}</style></head>
      <body><nav>menu</nav><article><h1>Pot Odds</h1><p>Compare price to equity.</p></article>
      <footer>copyright</footer><script>track()</script></body></html>
    """
    document = extract_file("page.html", markup.encode())
    assert "Compare price to equity." in document.text
    assert "menu" not in document.text
    assert "track()" not in document.text
    assert document.title == "Pot Odds"


def test_arxiv_abstract_links_are_pointed_at_the_pdf():
    assert (
        _normalize_arxiv("https://arxiv.org/abs/1706.03762")
        == "https://arxiv.org/pdf/1706.03762"
    )
    # Anything else is left alone.
    assert _normalize_arxiv("https://example.com/x") == "https://example.com/x"


def test_unsupported_files_say_what_is_supported():
    with pytest.raises(UnsupportedSourceError, match=r"\.epub"):
        extract_file("lecture.pptx", b"binary")


def test_html_to_text_survives_without_beautifulsoup(monkeypatch):
    """The crude fallback must still produce prose, not markup."""

    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "bs4":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    text = html_to_text("<p>Gradients <b>shrink</b>.</p><script>x()</script>")
    assert "Gradients" in text and "shrink" in text
    assert "<" not in text and "x()" not in text


def test_folder_ingest_skips_unsupported_files_and_saves_the_rest(db, tmp_path):
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "keep.md").write_text("# Keep\nGradients shrink through saturating activations.")
    (folder / "skip.png").write_bytes(b"not a picture")
    (folder / ".hidden.md").write_text("should be ignored")
    nested = folder / "more"
    nested.mkdir()
    (nested / "also.txt").write_text("Batch norm estimates get noisy at small batches.")

    provider = ScriptedProvider([{"title": "A concept", "summary": "s"}])
    job_id = db.enqueue_job("ingest_folder", {"folder": str(folder), "generate": False})
    JobWorker(db, lambda: provider).run_once()
    result = db.get_job(job_id)
    assert result["status"] == "succeeded"
    assert result["result"]["files"] == 2
    assert result["result"]["failed"] == 0
    titles = {row["title"] for row in db.list_sources()}
    assert "Keep" in titles


def test_iter_supported_files_ignores_hidden_and_unknown_types(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "a.md").write_text("a")
    (folder / "b.png").write_bytes(b"x")
    (folder / ".secret.md").write_text("no")
    found = [path.name for path in iter_supported_files(folder)]
    assert found == ["a.md"]
