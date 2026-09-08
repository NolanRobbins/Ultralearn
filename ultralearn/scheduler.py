"""Concept-level spaced repetition and grading.

The scheduler deliberately knows nothing about concrete question wording. It
schedules concepts, then the UI/generation layer picks a question variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ReviewState:
    ease: float
    interval: int
    repetitions: int
    due: str


def derive_quality(correct: bool, confidence: int) -> int:
    """Map correctness and pre-answer confidence to an SM-2 quality grade.

    Confident misses are treated as dangerous illusions of knowing. They receive
    the harshest grade so the concept comes back quickly for drill.
    """

    confidence = max(1, min(5, int(confidence)))
    if correct:
        return min(5, 2 + confidence)
    if confidence >= 4:
        return 0
    if confidence == 3:
        return 1
    return 2


def schedule_review_state(
    ease: float,
    interval: int,
    repetitions: int,
    quality: int,
    today: date | None = None,
) -> ReviewState:
    """Return the next concept-level SM-2 state after one review."""

    today = today or date.today()
    quality = max(0, min(5, int(quality)))

    if quality < 3:
        next_reps = 0
        next_interval = 1
    else:
        next_reps = repetitions + 1
        if next_reps == 1:
            next_interval = 1
        elif next_reps == 2:
            next_interval = 6
        else:
            next_interval = max(1, round(interval * ease))

    next_ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    next_due = (today + timedelta(days=next_interval)).isoformat()

    return ReviewState(
        ease=next_ease,
        interval=next_interval,
        repetitions=next_reps,
        due=next_due,
    )
