"""Request and response models for the Ultralearn API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    provider: str
    available: bool
    ready: bool
    message: str


class QuestionOut(BaseModel):
    id: int
    concept_id: int
    concept_title: str
    topic_slug: str
    question_type: str
    prompt: str
    options: list[str]
    bloom: str
    #: True when the learner must write an answer rather than pick one. Free
    #: recall is the default; multiple choice is the warmup.
    written: bool
    mode: Literal["due", "practice", "drill"]
    #: Open misconceptions on this concept, shown after answering.
    misconceptions: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    items: list[QuestionOut]
    total: int


class RevealRequest(BaseModel):
    question_id: int


class RevealResponse(BaseModel):
    expected_answer: str
    explanation: str
    answer_index: int | None = None
    answer_indices: list[int] = Field(default_factory=list)


class GradeRequest(BaseModel):
    question_id: int
    answer: str
    confidence: int = Field(default=3, ge=1, le=5)


class GradeResponse(BaseModel):
    verdict: Literal["correct", "partial", "incorrect"]
    score: int
    missing: list[str]
    misconception: str
    probe: str
    fix: str
    expected_answer: str
    explanation: str
    graded_by: str


class ReviewRequest(BaseModel):
    concept_id: int
    question_id: int
    correct: bool
    confidence: int = Field(default=3, ge=1, le=5)
    latency_seconds: float | None = None
    answer_text: str = ""
    mode: Literal["due", "practice", "drill"] = "due"
    score: int | None = None
    graded_by: str = "self"
    critique: str = ""
    misconception: str = ""


class ReviewResponse(BaseModel):
    concept_id: int
    mastery: float
    due: str
    leech: bool
    resolved_misconceptions: int


class TodayResponse(BaseModel):
    due: int
    concepts: int
    questions: int
    sources: int
    reviews: int
    leeches: int
    open_misconceptions: int
    streak_days: int
    reviewed_today: int
    estimated_minutes: int
    recent_days: list[dict[str, Any]]


class IngestRequest(BaseModel):
    text: str = ""
    url: str = ""
    title: str = ""
    source_type: str = "note"
    topic_slug: str = ""
    #: Generate questions after saving. Off means "just file the material".
    generate: bool = True


class JobOut(BaseModel):
    id: int
    kind: str
    label: str
    status: str
    progress: float
    detail: str
    result: dict[str, Any]
    error: str | None
    created_at: str
    updated_at: str


class ConceptOut(BaseModel):
    id: int
    title: str
    topic_slug: str
    mastery: float
    due: str
    leech: bool
    question_count: int


class SourceOut(BaseModel):
    id: int
    type: str
    title: str
    author: str | None
    chunk_count: int
    created_at: str


class SearchHit(BaseModel):
    kind: str
    ref_id: int
    title: str
    snippet: str
