"""Question generation orchestration and deduplication."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from .db import KnowledgeDB
from .dedup import QuestionDeduper
from .models import Concept, ProviderQuestion
from .providers import Provider, ProviderError


DEFAULT_QUIZ_SIZE = 10
GENERATION_BATCH_SIZE = 5

ProgressCallback = Callable[[int, int, dict[str, Any] | None], None]


@dataclass(frozen=True)
class SaveResult:
    saved: int
    duplicates: int


def save_generated_questions(
    db: KnowledgeDB,
    questions: list[ProviderQuestion],
    source_id: int | None = None,
    chunk_id: int | None = None,
) -> SaveResult:
    """Persist generated questions, linking each concept to its best-matching chunk.

    When no explicit chunk is given, the source's chunk most similar to the
    question is chosen, so concepts from a long document point at the right
    passage instead of all pointing at the first chunk.
    """

    saved = 0
    duplicates = 0
    for question in questions:
        target_chunk = chunk_id
        if target_chunk is None and source_id is not None:
            target_chunk = db.best_chunk_for_text(
                source_id, f"{question.concept_title}. {question.prompt}"
            )
        question_id = db.add_provider_question(question, source_id=source_id, chunk_id=target_chunk)
        if question_id is None:
            duplicates += 1
        else:
            saved += 1
    return SaveResult(saved=saved, duplicates=duplicates)


def generate_fresh_variant(
    db: KnowledgeDB,
    provider: Provider,
    concept: Concept,
    count: int = 1,
    bloom_hint: str = "",
) -> list[ProviderQuestion]:
    """Ask a provider for fresh variants of a scheduled concept.

    Context comes from the concept's linked chunks when they exist; otherwise the
    semantic index pulls the closest passages from every source, so overlapping
    material contributes wherever it lives.
    """

    context = db.source_context_for_concept(concept.id)
    if not context:
        matches = db.semantic_chunks(f"{concept.title}. {concept.summary}", k=3)
        context = "\n\n".join(match["text"] for match in matches)
    if not context:
        context = f"{concept.title}\n\n{concept.summary}"
    existing_prompts = db.existing_prompts_for_concept(concept.id)
    generated = provider.generate_questions(
        text=context,
        n=count,
        topic_slug=concept.topic_slug,
        concept_title=concept.title,
        bloom_hint=bloom_hint,
        avoid_prompts=existing_prompts,
    )
    existing = QuestionDeduper(existing_prompts)
    unique = [question for question in generated if not existing.is_duplicate(question.prompt)]
    if not unique:
        raise ProviderError("The provider only returned duplicates for this concept.")
    return unique


def generate_questions_batched(
    provider: Provider,
    text: str,
    total: int = DEFAULT_QUIZ_SIZE,
    batch_size: int = GENERATION_BATCH_SIZE,
    topic_slug: str = "general",
    source_title: str = "",
    bloom_hint: str = "",
    avoid_prompts: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[ProviderQuestion]:
    """Generate ``total`` questions in small batches so no single LLM call is huge.

    Small batches keep each subprocess/API call fast (avoiding timeouts), let the UI
    report progress and usage between calls, and let later batches steer away from
    the prompts produced by earlier ones.
    """

    total = max(1, total)
    batch_size = max(1, batch_size)
    batches = math.ceil(total / batch_size)
    avoid = list(avoid_prompts or [])
    collected: list[ProviderQuestion] = []
    last_error: ProviderError | None = None

    for batch_index in range(batches):
        remaining = total - len(collected)
        if remaining <= 0:
            break
        generated = _generate_batch_with_retry(
            provider,
            text=text,
            n=min(batch_size, remaining),
            topic_slug=topic_slug,
            source_title=source_title,
            bloom_hint=bloom_hint,
            avoid=avoid,
        )
        if isinstance(generated, ProviderError):
            last_error = generated
            if on_progress is not None:
                on_progress(batch_index + 1, batches, provider.last_usage)
            continue
        deduper = QuestionDeduper(avoid)
        fresh = [question for question in generated if not deduper.is_duplicate(question.prompt)]
        collected.extend(fresh)
        avoid.extend(question.prompt for question in fresh)
        if on_progress is not None:
            on_progress(batch_index + 1, batches, provider.last_usage)

    if not collected:
        if last_error is not None:
            raise last_error
        raise ProviderError("The provider produced no new, non-duplicate questions.")
    return collected


def _generate_batch_with_retry(
    provider: Provider,
    text: str,
    n: int,
    topic_slug: str,
    source_title: str,
    bloom_hint: str,
    avoid: list[str],
    attempts: int = 2,
) -> list[ProviderQuestion] | ProviderError:
    """Run one generation batch, retrying transient failures (e.g. malformed JSON).

    Returns the questions on success, or the last ProviderError so the caller can
    continue with other batches instead of aborting the whole round.
    """

    last_error: ProviderError | None = None
    for _ in range(max(1, attempts)):
        try:
            return provider.generate_questions(
                text=text,
                n=n,
                topic_slug=topic_slug,
                source_title=source_title,
                bloom_hint=bloom_hint,
                avoid_prompts=avoid,
            )
        except ProviderError as exc:
            last_error = exc
    return last_error if last_error is not None else ProviderError("Generation failed.")
