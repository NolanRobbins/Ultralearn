"""Zero-friction ingestion.

Dropping material used to mean filling in a source type, title, author,
identifier, topic slug and Bloom bias, waiting out a blocking generation call,
then ticking a Keep box on every question. Almost none of that was a decision
worth making, so none of it is asked for here.

One drop becomes one job: extract, chunk, let the model name the concepts,
classify the topic, generate questions, dedup, save. Reviewing the result is an
audit the learner can choose to do, not a gate they must pass.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from .db import KnowledgeDB, slugify
from .generation import GENERATION_BATCH_SIZE, save_generated_questions
from .jobs import ProgressReporter, register
from .loaders import UnsupportedSourceError, extract_file, fetch_url, iter_supported_files
from .providers import Provider, ProviderError

#: Concepts pulled from one source in a single pass. Enough for a chapter
#: without producing a queue the learner will never get through.
MAX_CONCEPTS_PER_SOURCE = 12

#: Questions per extracted concept.
QUESTIONS_PER_CONCEPT = 2

CONCEPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic_slug": {"type": "string"},
        "source_title": {"type": "string"},
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["title", "summary"],
            },
        },
    },
    "required": ["topic_slug", "concepts"],
}

CONCEPT_PROMPT = """You are indexing study material for Ultralearn, a personal teacher.

Identify the distinct ideas or skills in this excerpt that are worth ingraining \
permanently. A concept is one thing a learner could be tested on and either knows or \
does not: "backprop chain rule", "pot odds vs implied odds", "why batch norm breaks at \
small batch sizes". Not a section heading, not a whole topic.

Rules:
- At most {max_concepts} concepts. Fewer is better than padding with trivia.
- Skip anything that is only navigational, bibliographic, or administrative.
- Each summary must state the actual idea in one or two sentences, not describe what \
the passage is about. "Explains gradients" is useless; "gradients shrink multiplicatively \
through saturating activations, so early layers stop learning" is a concept.
- Choose one topic_slug for the whole source from this list where it fits: \
{topics}. Invent a short lowercase slug only if none apply.
- Suggest a concise source_title if the material has an obvious one.

EXCERPT:
\"\"\"{text}\"\"\"

Return ONLY a JSON object, no prose and no code fences:
{{
  "topic_slug": "one slug for the whole source",
  "source_title": "a concise title, or \\"\\" if unclear",
  "concepts": [{{"title": "one precise idea", "summary": "what it actually says"}}]
}}"""


@register("ingest")
def run_ingest(
    db: KnowledgeDB,
    provider: Provider,
    payload: dict[str, Any],
    report: ProgressReporter,
) -> dict[str, Any]:
    """Take dropped material all the way to saved, answerable questions."""

    report(0.05, "Reading source")
    document = _load(payload)
    if not document.text.strip():
        raise UnsupportedSourceError("That source produced no readable text.")

    title = (payload.get("title") or "").strip() or document.title or "Untitled source"
    report(0.15, f"Saving {title}")
    source_id = db.add_source(
        document.source_type,
        title,
        document.author,
        document.identifier,
        tags=[payload["topic_slug"]] if payload.get("topic_slug") else [],
    )
    chunk_ids = db.add_content(source_id, document.text)

    result: dict[str, Any] = {
        "source_id": source_id,
        "title": title,
        "chunks": len(chunk_ids),
        "concepts": 0,
        "questions": 0,
        "duplicates": 0,
    }
    if not payload.get("generate", True):
        report(1.0, f"Saved {len(chunk_ids)} passages")
        return result

    report(0.25, "Finding the concepts worth learning")
    topic_slug, concepts = extract_concepts(
        provider, document.text, db, preferred_topic=payload.get("topic_slug", "")
    )
    if not concepts:
        report(1.0, "Saved, but no concepts could be identified")
        return result
    result["concepts"] = len(concepts)

    saved_questions, duplicates = _write_questions(
        db, provider, document.text, concepts, topic_slug, title, source_id, report
    )
    result["questions"] = saved_questions
    result["duplicates"] = duplicates
    report(1.0, f"{saved_questions} questions across {len(concepts)} concepts")
    return result


@register("ingest_folder")
def run_ingest_folder(
    db: KnowledgeDB,
    provider: Provider,
    payload: dict[str, Any],
    report: ProgressReporter,
) -> dict[str, Any]:
    """Ingest every supported file in a dropped folder, one source each."""

    paths = iter_supported_files(payload["folder"])
    if not paths:
        raise UnsupportedSourceError(
            "That folder had no PDF, Word, EPUB, Markdown, HTML, or text files."
        )

    totals = {"files": 0, "concepts": 0, "questions": 0, "duplicates": 0, "failed": 0}
    for index, path in enumerate(paths):
        report(index / len(paths), f"Reading {path.name}")
        try:
            child = run_ingest(
                db,
                provider,
                {
                    "raw": path.read_bytes().hex(),
                    "filename": path.name,
                    "generate": payload.get("generate", True),
                },
                report,
            )
        except (UnsupportedSourceError, ProviderError):
            totals["failed"] += 1
            continue
        totals["files"] += 1
        totals["concepts"] += int(child.get("concepts") or 0)
        totals["questions"] += int(child.get("questions") or 0)
        totals["duplicates"] += int(child.get("duplicates") or 0)
    report(1.0, f"{totals['files']} files from the folder")
    return totals


@register("generate")
def run_generate(
    db: KnowledgeDB,
    provider: Provider,
    payload: dict[str, Any],
    report: ProgressReporter,
) -> dict[str, Any]:
    """Write more questions from a source already in the library."""

    source_id = int(payload["source_id"])
    title = payload.get("title") or f"Source {source_id}"
    text = db.source_text(source_id)
    if not text.strip():
        raise UnsupportedSourceError("That source has no stored text to generate from.")

    report(0.2, f"Finding concepts in {title}")
    topic_slug, concepts = extract_concepts(provider, text, db)
    if not concepts:
        return {"source_id": source_id, "concepts": 0, "questions": 0, "duplicates": 0}

    questions, duplicates = _write_questions(
        db, provider, text, concepts, topic_slug, title, source_id, report
    )
    report(1.0, f"{questions} new questions")
    return {
        "source_id": source_id,
        "concepts": len(concepts),
        "questions": questions,
        "duplicates": duplicates,
    }


@register("generate_focus")
def run_generate_focus(
    db: KnowledgeDB,
    provider: Provider,
    payload: dict[str, Any],
    report: ProgressReporter,
) -> dict[str, Any]:
    """Write questions from the passages closest to a Focus query.

    This is how overlapping sources contribute: the vector index pulls the
    relevant chunks wherever they live, then generation runs against that mix.
    """

    query = str(payload.get("query") or "").strip()
    if not query:
        raise UnsupportedSourceError("Nothing to focus on.")

    report(0.15, f"Finding passages about: {query}")
    matches = db.semantic_chunks(query, k=6)
    if not matches:
        raise UnsupportedSourceError("Nothing in the library is close to that yet. Add some material first.")

    text = "\n\n".join(match["text"] for match in matches)
    # Attribute new questions to the source that contributed the closest chunk
    # so they still trace back to real material.
    source_id = int(matches[0]["source_id"])
    title = str(matches[0]["source_title"])

    report(0.3, "Finding the concepts worth learning")
    topic_slug, concepts = extract_concepts(provider, text, db)
    if not concepts:
        return {"concepts": 0, "questions": 0, "duplicates": 0, "query": query}

    questions, duplicates = _write_questions(
        db, provider, text, concepts, topic_slug, title, source_id, report
    )
    report(1.0, f"{questions} questions on {query}")
    return {
        "query": query,
        "concepts": len(concepts),
        "questions": questions,
        "duplicates": duplicates,
        "source_id": source_id,
    }


@register("coaching")
def run_coaching(
    db: KnowledgeDB,
    provider: Provider,
    payload: dict[str, Any],
    report: ProgressReporter,
) -> dict[str, Any]:
    """Write a diagnostic report from the review history.

    A job rather than a request: it reads the whole history and can take a while,
    and there is no reason for the learner to sit and watch it.
    """

    report(0.2, "Reading your review history")
    context = db.coaching_context()
    if not context.strip():
        raise ProviderError("There is no review history to analyse yet.")

    # Misconceptions are the most diagnostic thing on record, so they go in
    # explicitly rather than being left for the model to infer from accuracy.
    open_items = db.open_misconceptions(limit=30)
    if open_items:
        lines = "\n".join(
            f"- {row['concept_title']}: {row['statement']} (seen {row['times_seen']}x)"
            for row in open_items
        )
        context = f"{context}\n\nUNRESOLVED MISCONCEPTIONS:\n{lines}"

    report(0.5, "Asking for an honest assessment")
    text = provider.analyze_weakspots(context)
    db.save_coaching_report(provider.name, text)
    report(1.0, "Report ready")
    return {"characters": len(text)}


def extract_concepts(
    provider: Provider,
    text: str,
    db: KnowledgeDB,
    preferred_topic: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Ask the provider to name the concepts in a source and classify its topic."""

    known = [row["slug"] for row in db.list_topics()]
    prompt = CONCEPT_PROMPT.format(
        max_concepts=MAX_CONCEPTS_PER_SOURCE,
        topics=", ".join(known) or "general",
        text=text[:14000],
    )
    complete = getattr(provider, "_complete", None)
    if complete is None:
        raise ProviderError("This provider cannot extract concepts.")
    payload = _first_json_object(complete(prompt, schema=CONCEPT_SCHEMA))
    if not payload:
        raise ProviderError("The provider did not return a readable concept list.")

    topic_slug = preferred_topic or slugify(str(payload.get("topic_slug") or "general"))
    concepts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload.get("concepts") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        concepts.append({"title": title, "summary": str(item.get("summary") or "").strip()})
        if len(concepts) >= MAX_CONCEPTS_PER_SOURCE:
            break
    return topic_slug or "general", concepts


def _write_questions(
    db: KnowledgeDB,
    provider: Provider,
    text: str,
    concepts: list[dict[str, str]],
    topic_slug: str,
    title: str,
    source_id: int,
    report: ProgressReporter,
) -> tuple[int, int]:
    """Generate and save questions for each concept. One failure does not sink the rest."""

    total_questions = 0
    total_duplicates = 0
    for index, concept in enumerate(concepts):
        fraction = 0.3 + 0.65 * (index / max(1, len(concepts)))
        report(fraction, f"Writing questions: {concept['title']}")
        context = _context_for(text, concept)
        try:
            generated = provider.generate_questions(
                text=context,
                n=min(QUESTIONS_PER_CONCEPT, GENERATION_BATCH_SIZE),
                topic_slug=topic_slug,
                source_title=title,
                concept_title=concept["title"],
            )
        except ProviderError:
            continue
        anchored = [
            replace(
                question,
                concept_title=concept["title"],
                concept_summary=concept["summary"] or question.concept_summary,
                topic_slug=topic_slug,
            )
            for question in generated
        ]
        saved = save_generated_questions(db, anchored, source_id=source_id)
        total_questions += saved.saved
        total_duplicates += saved.duplicates
    return total_questions, total_duplicates


def _load(payload: dict[str, Any]):
    """Resolve an ingest payload into a document, whatever form it arrived in."""

    if payload.get("raw"):
        data = bytes.fromhex(payload["raw"])
        return extract_file(payload.get("filename", "upload"), data)
    if payload.get("url"):
        return fetch_url(payload["url"])

    from .loaders import ExtractedDocument, _markdown_title

    text = payload.get("text", "")
    return ExtractedDocument(
        text=text,
        title=payload.get("title") or _markdown_title(text),
        source_type=payload.get("source_type", "note"),
    )


def _context_for(text: str, concept: dict[str, str], window: int = 6000) -> str:
    """Give the generator the part of the source that discusses this concept.

    A cheap keyword window rather than an embedding lookup: the chunks are not
    indexed yet at this point in the pipeline, and being approximately right is
    enough to keep the question anchored to real material.
    """

    if len(text) <= window:
        return text
    needle = concept["title"].lower()
    position = text.lower().find(needle)
    if position == -1:
        words = [word for word in re.findall(r"[a-z]{5,}", needle)]
        for word in words:
            position = text.lower().find(word)
            if position != -1:
                break
    if position == -1:
        return text[:window]
    start = max(0, position - window // 3)
    return text[start : start + window]


def _first_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    candidate = text[start : end + 1]
    for attempt in (candidate, re.sub(r",(\s*[}\]])", r"\1", candidate)):
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
