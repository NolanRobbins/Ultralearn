"""Small typed records used by the core learning engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Concept:
    id: int
    title: str
    summary: str
    topic_slug: str
    mastery: float
    leech: bool
    ease: float
    interval: int
    repetitions: int
    due: str


@dataclass(frozen=True)
class Question:
    id: int
    concept_id: int
    question_type: str
    prompt: str
    options: list[str]
    answer: dict[str, Any]
    explanation: str
    bloom: str
    ask_count: int


@dataclass(frozen=True)
class ProviderQuestion:
    """Question payload returned by an LLM provider before persistence."""

    concept_title: str
    concept_summary: str
    topic_slug: str
    question_type: str
    prompt: str
    options: list[str]
    answer: dict[str, Any]
    explanation: str
    bloom: str
