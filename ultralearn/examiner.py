"""The examiner: strict grading of written answers.

Free recall only teaches if the grading is honest. Earlier versions asked the
learner to self-grade with an "I got it" button, which quietly rewards vague
recall — exactly the illusion of knowing that spaced repetition is supposed to
destroy. Grading here returns a structured verdict so a misconception can be
named, stored, and re-tested rather than read once and forgotten.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .providers import Provider, ProviderError

#: Schema handed to providers that support constrained output.
GRADE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 5},
        "missing": {"type": "array", "items": {"type": "string"}},
        "misconception": {"type": "string"},
        "probe": {"type": "string"},
        "fix": {"type": "string"},
    },
    "required": ["verdict", "score", "missing", "misconception", "probe", "fix"],
}

GRADING_PROMPT = """You are Ultralearn's examiner. You are demanding, precise, and \
impossible to satisfy with vagueness. Your job is to find out whether the learner \
actually understands the mechanism, not whether they can produce the right vocabulary.

Grade against these rules:
- A correct label with no mechanism is NOT correct. It is partial at best.
- Hedging ("something like", "kind of", "it depends") without committing is not credit.
- If the answer would fall apart under one follow-up question, it is not correct.
- Reserve "correct" for answers that state the mechanism and its boundary. Reserve a \
score of 5 for an answer you could not improve.
- Name the specific misconception, not a generic one. If there is genuinely no \
misconception, return an empty string for it.
- The probe must be a question this specific answer fails to settle.

Question:
{question}

Reference answer:
{expected}

The learner's answer:
\"\"\"{answer}\"\"\"

Return ONLY a JSON object with these keys, no prose and no code fences:
{{
  "verdict": "correct" | "partial" | "incorrect",
  "score": integer 0-5,
  "missing": ["each specific thing the answer failed to state"],
  "misconception": "the exact wrong belief this answer reveals, or \\"\\" if none",
  "probe": "one follow-up question that would expose whether they truly understand it",
  "fix": "one concrete correction to make before moving on"
}}"""


@dataclass(frozen=True)
class GradeResult:
    verdict: str = "partial"
    score: int = 0
    missing: list[str] = field(default_factory=list)
    misconception: str = ""
    probe: str = ""
    fix: str = ""
    graded_by: str = "examiner"

    @property
    def correct(self) -> bool:
        return self.verdict == "correct"

    @classmethod
    def unavailable(cls, reason: str) -> "GradeResult":
        """Fall back to self-grading when no provider can grade.

        Deliberately not scored: a missing examiner must not be recorded as if
        the learner had passed.
        """

        return cls(
            verdict="partial",
            score=0,
            missing=[],
            misconception="",
            probe="Compare your answer to the reference and find the first thing you left out.",
            fix=reason,
            graded_by="self",
        )


def grade_answer(
    provider: Provider,
    question: str,
    expected_answer: str,
    learner_answer: str,
) -> GradeResult:
    """Grade a written answer, returning a structured verdict."""

    if not learner_answer.strip():
        return GradeResult(
            verdict="incorrect",
            score=0,
            missing=["No answer was given."],
            misconception="",
            probe="What is the first thing you would need to know to answer this at all?",
            fix="Attempt an answer even when unsure; a wrong guess is diagnostic, a blank is not.",
        )

    prompt = GRADING_PROMPT.format(
        question=question, expected=expected_answer or "(none recorded)", answer=learner_answer
    )
    complete = getattr(provider, "_complete", None)
    if complete is None:
        return GradeResult.unavailable("This provider cannot grade written answers.")
    try:
        raw = complete(prompt, schema=GRADE_SCHEMA)
    except ProviderError:
        raise
    return parse_grade(raw)


def parse_grade(raw: str) -> GradeResult:
    """Parse the examiner's response, tolerating fences and surrounding prose."""

    payload = _first_json_object(raw)
    if payload is None:
        return GradeResult.unavailable("The examiner's response could not be read.")

    verdict = str(payload.get("verdict", "partial")).strip().lower()
    if verdict not in {"correct", "partial", "incorrect"}:
        verdict = "partial"

    try:
        score = int(payload.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(5, score))

    missing = payload.get("missing") or []
    if not isinstance(missing, list):
        missing = [str(missing)]

    # A high score with a "partial" verdict, or vice versa, means the model
    # hedged. Trust the verdict, since that is what drives scheduling.
    if verdict == "correct" and score < 3:
        verdict = "partial"

    return GradeResult(
        verdict=verdict,
        score=score,
        missing=[str(item).strip() for item in missing if str(item).strip()],
        misconception=str(payload.get("misconception") or "").strip(),
        probe=str(payload.get("probe") or "").strip(),
        fix=str(payload.get("fix") or "").strip(),
    )


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
