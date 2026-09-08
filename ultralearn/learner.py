"""Adaptive learner-model helpers for sessions and reports."""

from __future__ import annotations

from dataclasses import dataclass

from .db import KnowledgeDB
from .models import Concept


@dataclass(frozen=True)
class SessionItem:
    """One quiz slot: a concept plus whether it's extra practice (not due)."""

    concept: Concept
    practice: bool


def build_adaptive_session(db: KnowledgeDB, limit: int = 20) -> list[Concept]:
    """Blend due concepts, leeches, and low-mastery concepts into one queue."""

    due = db.get_due_concepts(limit=limit * 2, include_new=True)
    leeches = [concept for concept in due if concept.leech]
    low_mastery = sorted(
        [concept for concept in due if not concept.leech],
        key=lambda concept: (concept.mastery, concept.due),
    )

    queue: list[Concept] = []
    while len(queue) < limit and (leeches or low_mastery):
        if leeches:
            queue.append(leeches.pop(0))
        for _ in range(2):
            if low_mastery and len(queue) < limit:
                queue.append(low_mastery.pop(0))
    seen: set[int] = set()
    unique_queue: list[Concept] = []
    for concept in queue:
        if concept.id not in seen:
            seen.add(concept.id)
            unique_queue.append(concept)
    return unique_queue[:limit]


def build_session(db: KnowledgeDB, limit: int = 10) -> list[SessionItem]:
    """Build candidates for one round: due concepts first, then practice fill.

    Returns more candidates than ``limit`` so the caller can skip concepts that
    have no usable question and still fill a round. Practice items only appear
    after every due concept, so scheduled reviews always take priority.
    """

    due = build_adaptive_session(db, limit=limit * 2)
    items = [SessionItem(concept=concept, practice=False) for concept in due]
    extra = db.get_practice_concepts(
        limit=limit * 2,
        exclude_ids=[concept.id for concept in due],
    )
    items.extend(SessionItem(concept=concept, practice=True) for concept in extra)
    return items
