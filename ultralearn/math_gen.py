"""Turn a library concept or Focus query into a formula drill."""

from __future__ import annotations

import json
import re
from typing import Any

from .db import KnowledgeDB, slugify
from .jobs import ProgressReporter, register
from .providers import Provider, ProviderError

MATH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "latex": {"type": "string"},
        "spoken": {"type": "string"},
        "intuition": {"type": "string"},
        "key_phrases": {"type": "array", "items": {"type": "string"}},
        "blanks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "answer": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                },
            },
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "name": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
    },
    "required": ["title", "latex", "spoken", "key_phrases"],
}

_PROMPT = """You are writing a formula drill for Ultralearn.

The learner will see the equation in LaTeX and must:
1. Say it in English (the mechanism, not the symbol names alone).
2. Fill in a missing piece.
3. Explain why a particular term is there.

Pick the ONE central equation of this material. Do not invent a toy identity.

Concept: {title}
{summary}

Source excerpt:
\"\"\"{excerpt}\"\"\"

Return ONLY JSON with:
{{
  "title": "short name",
  "latex": "valid KaTeX, no $ fences",
  "spoken": "one or two fluent English sentences reading the equation aloud",
  "intuition": "why this form exists — what would break if a piece were missing",
  "key_phrases": ["3-6 short phrases a good spoken answer must hit"],
  "blanks": [{{"id": "b1", "prompt": "question about a missing piece", "answer": "short", "aliases": [], "why": "why that piece is there"}}],
  "terms": [{{"symbol": "latex symbol", "name": "plain name", "why": "why this term earns its place"}}]
}}
"""


@register("generate_math")
def run_generate_math(
    db: KnowledgeDB,
    provider: Provider,
    payload: dict[str, Any],
    report: ProgressReporter,
) -> dict[str, Any]:
    concept_id = payload.get("concept_id")
    query = str(payload.get("query") or "").strip()
    title = ""
    summary = ""
    excerpt = ""
    if concept_id:
        concept = db.get_concept(int(concept_id))
        if concept is None:
            raise ProviderError("No such concept.")
        title = concept.title
        summary = concept.summary
        matches = db.semantic_chunks(concept.title, k=3)
        excerpt = "\n\n".join(match["text"] for match in matches[:3])
        report(0.2, f"Reading passages for {title}")
    else:
        if not query:
            raise ProviderError("Say which formula to extract.")
        title = query
        matches = db.semantic_chunks(query, k=4)
        if not matches:
            raise ProviderError("Nothing in the library is close to that yet.")
        excerpt = "\n\n".join(match["text"] for match in matches)
        report(0.2, f"Reading passages about {query}")

    report(0.5, "Writing the formula drill")
    complete = getattr(provider, "_complete", None)
    if not callable(complete):
        raise ProviderError("Formula generation needs an LLM provider.")
    raw = complete(
        _PROMPT.format(title=title, summary=summary or "(no summary)", excerpt=excerpt[:6000]),
        MATH_SCHEMA,
    )
    data = _parse(raw)
    slug_base = slugify(str(data.get("title") or title))[:80]
    formula_id = db.add_math_formula(
        slug=f"{slug_base}-from-library",
        title=str(data.get("title") or title)[:120],
        latex=str(data.get("latex") or "").strip(),
        spoken=str(data.get("spoken") or "").strip(),
        intuition=str(data.get("intuition") or "").strip(),
        key_phrases=[str(item) for item in data.get("key_phrases") or []],
        blanks=list(data.get("blanks") or []),
        terms=list(data.get("terms") or []),
        tags=["from-library"],
        concept_id=int(concept_id) if concept_id else None,
        concept_hints=[title] if title else [],
    )
    report(1.0, "Formula drill saved")
    return {"formula_id": formula_id, "title": data.get("title") or title}


def _parse(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("The model did not return a usable formula JSON.") from exc
    if not str(data.get("latex") or "").strip() or not str(data.get("spoken") or "").strip():
        raise ProviderError("The formula drill was missing LaTeX or the spoken form.")
    return data
