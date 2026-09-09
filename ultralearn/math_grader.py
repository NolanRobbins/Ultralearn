"""Local grading for math recitation, fill-in, and 'why is this term here'."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def normalize(value: str) -> str:
    text = value.lower().replace("$", " ")
    text = text.replace("^{", "^").replace("{", " ").replace("}", " ")
    text = text.replace("\\", " ").replace("_", " ")
    text = re.sub(r"[^a-z0-9.+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _hits_phrase(answer: str, phrase: str) -> bool:
    haystack = normalize(answer)
    needle = normalize(phrase)
    if not needle:
        return True
    if needle in haystack:
        return True
    words = needle.split()
    return bool(words) and all(word in haystack.split() or word in haystack for word in words)


@dataclass
class PhraseGrade:
    passed: bool
    score: float
    hits: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    verdict: str = "partial"


def grade_phrases(answer: str, phrases: list[str], threshold: float = 0.7) -> PhraseGrade:
    if not phrases:
        return PhraseGrade(passed=bool(answer.strip()), score=1.0 if answer.strip() else 0.0, verdict="correct" if answer.strip() else "incorrect")
    hits = [phrase for phrase in phrases if _hits_phrase(answer, phrase)]
    missing = [phrase for phrase in phrases if phrase not in hits]
    score = len(hits) / len(phrases)
    if score >= 0.999:
        verdict = "correct"
    elif score >= threshold:
        verdict = "partial"
    else:
        verdict = "incorrect"
    return PhraseGrade(
        passed=score >= threshold,
        score=score,
        hits=hits,
        missing=missing,
        verdict=verdict,
    )


_WHY_STOP = {
    "that",
    "this",
    "with",
    "from",
    "when",
    "every",
    "which",
    "would",
    "into",
    "then",
    "than",
    "their",
    "there",
    "about",
    "does",
    "just",
    "what",
    "where",
    "have",
    "been",
}


def why_phrases(why: str) -> list[str]:
    """Turn a gold 'why' into phrases a 50–70% keyword hit can pass."""

    sentences = [part.strip() for part in re.split(r"[.;]\s+", why) if len(part.strip()) > 20]
    if len(sentences) >= 2:
        return sentences
    words = [word for word in normalize(why).split() if len(word) > 3 and word not in _WHY_STOP]
    return words[:8] or ([why.strip()] if why.strip() else ["missing"])


def answers_match(given: str, expected: str, aliases: list[str] | None = None) -> bool:
    candidates = [expected, *(aliases or [])]
    got = normalize(given)
    if not got:
        return False
    for candidate in candidates:
        want = normalize(candidate)
        if got == want or want in got or got in want:
            return True
    return False
