"""Local embeddings for semantic retrieval across sources.

Prefers sentence-transformers (true semantic vectors, fully local after the
first model download). Falls back to a hashed bag-of-ngrams vectorizer with no
dependencies, so retrieval always works — just with keyword-level matching
instead of meaning-level matching. Vectors are tagged with the embedder name in
the database, so switching models simply triggers a re-index.
"""

from __future__ import annotations

import hashlib
import math
import re
from array import array
from typing import Protocol


_WORD_RE = re.compile(r"[a-z0-9]+")
_ST_MODEL = "all-MiniLM-L6-v2"


class Embedder(Protocol):
    """Anything that can turn texts into unit-norm vectors."""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Dependency-free fallback: hashed word uni/bigram vectors, L2-normalized.

    Cosine similarity on these vectors approximates keyword overlap. It is not
    truly semantic, but it keeps focus search working with zero setup.
    """

    name = "hashing-512"
    dim = 512

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        words = _WORD_RE.findall(text.lower())
        grams = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        for gram in grams:
            digest = hashlib.md5(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class SentenceTransformerEmbedder:
    """MiniLM sentence embeddings; local inference after a one-time model download."""

    name = f"st-{_ST_MODEL}"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(_ST_MODEL)

    def embed(self, texts: list[str]) -> list[list[float]]:
        rows = self._model.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in row] for row in rows]


_cached_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Best available embedder, cached for the process lifetime."""

    global _cached_embedder
    if _cached_embedder is None:
        try:
            _cached_embedder = SentenceTransformerEmbedder()
        except Exception:
            _cached_embedder = HashingEmbedder()
    return _cached_embedder


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; inputs are unit-norm so this is just a dot product."""

    return sum(x * y for x, y in zip(a, b))


def pack_vector(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    return list(array("f", blob))
