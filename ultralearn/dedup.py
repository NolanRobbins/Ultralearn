"""Question deduplication without requiring network embeddings."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher


_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_text(text: str) -> str:
    """Normalize text aggressively enough for duplicate detection."""

    return " ".join(_WORD_RE.findall(text.lower()))


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def similarity(a: str, b: str) -> float:
    left = normalize_text(a)
    right = normalize_text(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


class QuestionDeduper:
    """Reject exact and near-duplicate question prompts for a concept."""

    def __init__(self, existing_prompts: list[str], threshold: float = 0.88) -> None:
        self.existing_prompts = existing_prompts
        self.threshold = threshold
        self._fingerprints = {fingerprint(prompt) for prompt in existing_prompts}

    def is_duplicate(self, prompt: str) -> bool:
        if fingerprint(prompt) in self._fingerprints:
            return True
        return any(similarity(prompt, existing) >= self.threshold for existing in self.existing_prompts)
