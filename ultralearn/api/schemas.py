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
    code_problems: int = 0
    due_code: int = 0
    math_formulas: int = 0
    due_math: int = 0


class IngestRequest(BaseModel):
    text: str = ""
    url: str = ""
    title: str = ""
    source_type: str = "note"
    topic_slug: str = ""
    folder: str = ""
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
    code_count: int = 0
    math_count: int = 0


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
    via: str = "text"
    score: float | None = None


class CodeProblemOut(BaseModel):
    id: int
    slug: str
    title: str
    prompt: str
    starter: str
    difficulty: str
    tags: list[str]
    concept_id: int | None = None
    concept_title: str | None = None
    timeout_seconds: int = 8
    attempts: int = 0
    ever_passed: bool = False
    last_passed: bool | None = None
    last_code: str | None = None


class CodeRunRequest(BaseModel):
    problem_id: int
    code: str


class CodeCheckOut(BaseModel):
    name: str
    ok: bool
    error: str = ""


class CodeRunResponse(BaseModel):
    passed: bool
    checks: list[CodeCheckOut]
    stdout: str = ""
    stderr: str = ""
    runtime_ms: int = 0
    timed_out: bool = False
    error: str = ""


class MathBlankOut(BaseModel):
    id: str
    prompt: str


class MathTermOut(BaseModel):
    symbol: str
    name: str


class MathFormulaOut(BaseModel):
    id: int
    slug: str
    title: str
    latex: str
    intuition: str = ""
    tags: list[str] = Field(default_factory=list)
    concept_id: int | None = None
    concept_title: str | None = None
    blanks: list[MathBlankOut] = Field(default_factory=list)
    terms: list[MathTermOut] = Field(default_factory=list)
    attempts: int = 0
    ever_passed: bool = False


class MathGradeRequest(BaseModel):
    formula_id: int
    mode: Literal["speak", "fill", "why"]
    spoken: str = ""
    blanks: dict[str, str] = Field(default_factory=dict)
    term_symbol: str = ""
    why: str = ""


class MathGradeResponse(BaseModel):
    passed: bool
    verdict: str
    score: float
    hits: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    spoken: str = ""
    intuition: str = ""
    blank_results: list[dict[str, Any]] = Field(default_factory=list)
    term_why: str = ""
    fix: str = ""
