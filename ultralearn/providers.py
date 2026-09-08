"""Pluggable LLM providers for generation, critique, and coaching."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from .config import AppConfig
from .models import ProviderQuestion


QUESTION_TYPES = [
    "single_mcq",
    "multi_select",
    "cloze",
    "spot_error",
    "short_answer",
    "compare_contrast",
    "applied_scenario",
]


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete a requested LLM task."""


class Provider(ABC):
    name: str = "provider"
    #: Usage metadata from the most recent call (cost, tokens, duration), when known.
    last_usage: dict[str, Any] | None = None

    @abstractmethod
    def available(self) -> bool:
        """Return whether this provider can run in the current environment."""

    @abstractmethod
    def generate_questions(
        self,
        text: str,
        n: int,
        topic_slug: str,
        source_title: str = "",
        concept_title: str = "",
        bloom_hint: str = "",
        avoid_prompts: list[str] | None = None,
    ) -> list[ProviderQuestion]:
        """Generate varied active-recall questions from text or a concept summary."""

    @abstractmethod
    def critique(
        self,
        question: str,
        expected_answer: str,
        learner_answer: str,
    ) -> str:
        """Critique a Feynman explanation or short answer."""

    @abstractmethod
    def analyze_weakspots(self, report_context: str) -> str:
        """Produce a diagnostic coaching report from review history."""


class ManualProvider(Provider):
    name = "manual"

    def available(self) -> bool:
        return True

    def generate_questions(
        self,
        text: str,
        n: int,
        topic_slug: str,
        source_title: str = "",
        concept_title: str = "",
        bloom_hint: str = "",
        avoid_prompts: list[str] | None = None,
    ) -> list[ProviderQuestion]:
        raise ProviderError("Manual mode cannot auto-generate questions. Add them by hand.")

    def critique(self, question: str, expected_answer: str, learner_answer: str) -> str:
        return (
            "SCORE: self-grade required\n"
            "GAP: no LLM provider is active, so compare your answer against the expected answer precisely.\n"
            "FIX: rewrite the answer with the causal mechanism, not just the label."
        )

    def analyze_weakspots(self, report_context: str) -> str:
        return "No LLM provider is active. Use the weak-spot table for now, then run a provider-backed report later."


class PromptProvider(Provider):
    """Base class for providers that accept a single text prompt and return text."""

    def generate_questions(
        self,
        text: str,
        n: int,
        topic_slug: str,
        source_title: str = "",
        concept_title: str = "",
        bloom_hint: str = "",
        avoid_prompts: list[str] | None = None,
    ) -> list[ProviderQuestion]:
        prompt = build_generation_prompt(
            text, n, topic_slug, source_title, concept_title, bloom_hint, avoid_prompts
        )
        return parse_questions(self._complete(prompt))

    def critique(self, question: str, expected_answer: str, learner_answer: str) -> str:
        prompt = f"""You are Ultralearn's demanding examiner. Be precise, skeptical, and useful.

Question:
{question}

Expected answer:
{expected_answer}

Learner answer:
\"\"\"{learner_answer}\"\"\"

Respond in exactly this structure:
SCORE: x/5
MISCONCEPTION: the exact misconception, vagueness, or missing causal link
PROBE: one follow-up question that would expose whether they truly understand it
FIX: one concrete improvement they should make before moving on"""
        return self._complete(prompt).strip()

    def analyze_weakspots(self, report_context: str) -> str:
        prompt = f"""You are Ultralearn's diagnostic coach. Be honest, specific, and study-oriented.
Use the review history below to identify what is solid, what is fragile, and what to drill next.
Do not flatter. Name overconfidence and repeated misses directly.

Return sections:
SOLID:
FRAGILE:
LEECHED:
NEXT DRILLS:
WHY THIS ORDER:

Review context:
{report_context[:16000]}"""
        return self._complete(prompt).strip()

    @abstractmethod
    def _complete(self, prompt: str) -> str:
        """Run the provider-specific completion call."""


class ClaudeCodeProvider(PromptProvider):
    """Subprocess-backed provider for local Claude Code CLI usage.

    Uses ``--output-format json`` so each call reports cost, token counts, and
    duration, which the UI surfaces as running usage.
    """

    name = "claude_code"

    def __init__(self, command: str = "claude", timeout_seconds: int = 300) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        executable = shlex.split(self.command)[0] if self.command.strip() else "claude"
        return shutil.which(executable) is not None

    def _complete(self, prompt: str) -> str:
        parts = shlex.split(self.command)
        if not parts:
            parts = ["claude"]
        if any("{prompt}" in part for part in parts):
            cmd = [part.replace("{prompt}", prompt) for part in parts]
        else:
            cmd = parts + ["-p", prompt]
            if "--output-format" not in parts:
                cmd += ["--output-format", "json"]
        started = time.monotonic()
        try:
            # stdin must be closed: in -p mode the CLI can silently wait for
            # interactive input (e.g. when logged out) instead of erroring.
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ProviderError("Claude Code CLI was not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"Claude Code timed out after {self.timeout_seconds}s. Check that you are logged in "
                "(`claude` then /login) and that `claude -p 'ok'` works in a terminal; if it is just "
                "slow, raise the provider timeout in Settings."
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise ProviderError(f"Claude Code failed: {detail[:800]}")
        return self._extract_result(proc.stdout, elapsed_seconds=time.monotonic() - started)

    def _extract_result(self, stdout: str, elapsed_seconds: float | None = None) -> str:
        """Unwrap the Claude Code JSON envelope and record usage; pass raw text through."""

        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout
        if not isinstance(envelope, dict) or "result" not in envelope:
            return stdout
        usage = envelope.get("usage") or {}
        duration_ms = envelope.get("duration_ms")
        if duration_ms is None and elapsed_seconds is not None:
            duration_ms = int(elapsed_seconds * 1000)
        self.last_usage = {
            "provider": self.name,
            "cost_usd": envelope.get("total_cost_usd"),
            "duration_ms": duration_ms,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
        if envelope.get("is_error"):
            raise ProviderError(f"Claude Code returned an error: {str(envelope.get('result'))[:800]}")
        return str(envelope.get("result") or "")


class AnthropicProvider(PromptProvider):
    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, timeout_seconds: int = 90) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except Exception:
            return False
        return True

    def _complete(self, prompt: str) -> str:
        if not self.available():
            raise ProviderError("Anthropic provider needs the anthropic package and ANTHROPIC_API_KEY.")
        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key, timeout=self.timeout_seconds)
        msg = client.messages.create(
            model=self.model,
            max_tokens=5000,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")


class OpenAIProvider(PromptProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-5-mini", api_key: str | None = None, timeout_seconds: int = 90) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import openai  # noqa: F401
        except Exception:
            return False
        return True

    def _complete(self, prompt: str) -> str:
        if not self.available():
            raise ProviderError("OpenAI provider needs the openai package and OPENAI_API_KEY.")
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
        response = client.responses.create(model=self.model, input=prompt)
        return response.output_text


class OllamaProvider(PromptProvider):
    name = "ollama"

    def __init__(self, url: str, model: str, timeout_seconds: int = 90) -> None:
        self.url = url
        self.model = model
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        try:
            request = urllib.request.Request(
                self.url,
                data=json.dumps({"model": self.model, "prompt": "ping", "stream": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def _complete(self, prompt: str) -> str:
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"Ollama provider failed: {exc}") from exc
        return data.get("response", "")


def build_provider(
    name: str,
    config: AppConfig,
    anthropic_key: str = "",
    openai_key: str = "",
) -> Provider:
    normalized = (name or "claude_code").strip().lower()
    if normalized == "claude_code":
        return ClaudeCodeProvider(config.claude_command, config.provider_timeout_seconds)
    if normalized == "anthropic":
        return AnthropicProvider(config.model, anthropic_key or None, config.provider_timeout_seconds)
    if normalized == "openai":
        return OpenAIProvider(config.model, openai_key or None, config.provider_timeout_seconds)
    if normalized == "ollama":
        return OllamaProvider(config.ollama_url, config.ollama_model, config.provider_timeout_seconds)
    return ManualProvider()


def build_generation_prompt(
    text: str,
    n: int,
    topic_slug: str,
    source_title: str = "",
    concept_title: str = "",
    bloom_hint: str = "",
    avoid_prompts: list[str] | None = None,
) -> str:
    concept_instruction = (
        f"Focus on concept: {concept_title}.\n" if concept_title else "Infer precise concepts from the excerpt.\n"
    )
    bloom_instruction = f"Prefer Bloom level: {bloom_hint}.\n" if bloom_hint else ""
    avoid_instruction = ""
    if avoid_prompts:
        recent = "\n".join(f"- {prompt[:200]}" for prompt in avoid_prompts[-20:])
        avoid_instruction = (
            "\nThese questions were already asked. Every new question must test the material from a "
            f"DIFFERENT angle, scenario, or format than all of these:\n{recent}\n"
        )
    return f"""You are building Ultralearn, a rigorous personal teacher based on retrieval, retention, directness, drill, feedback, intuition, and metalearning.

Generate {n} active-recall question variants. They must test understanding rather than pattern recognition.
Use varied formats from: {", ".join(QUESTION_TYPES)}.
{concept_instruction}{bloom_instruction}{avoid_instruction}
Topic slug: {topic_slug}
Source: {source_title or "unspecified"}

Return ONLY a valid JSON array. No markdown fences, no commentary before or after.
Output must be strictly parseable JSON: escape every double quote inside a string as \\", and
do not use literal newlines inside string values. Each item must have:
{{
  "concept_title": "one precise idea or skill",
  "concept_summary": "1-2 sentence explanation of the concept",
  "topic_slug": "{topic_slug}",
  "question_type": one of {QUESTION_TYPES},
  "prompt": "question text",
  "options": ["..."] or [],
  "answer": {{"index": 0}} for single-choice, {{"indices": [0,2]}} for multi-select, or {{"text": "expected answer"}} for written formats,
  "explanation": "why the answer is right and what misconception a wrong answer reveals",
  "bloom": "recall"|"apply"|"analyze"
}}

Rules:
- NEVER copy sentences or distinctive phrasing from the excerpt. Paraphrase every idea in your own words.
- Invent NEW scenarios, numbers, examples, and contexts that are not in the excerpt, so answering requires
  applying the idea rather than recognizing the source text.
- Prefer transfer questions: "given this new situation, what happens / what's wrong / which applies and why."
- Prefer scenarios, comparisons, failure diagnosis, and spot-the-error prompts over definition checks.
- Make wrong options plausible misconceptions someone half-understanding the material would pick, not throwaways.
- For single_mcq and applied_scenario with options, provide exactly 4 plausible options.
- For multi_select, provide 4-6 options and at least 2 correct indices.
- For written formats, options must be [] and answer.text must be specific enough for strict grading.
- In "explanation", refer to choices by letter (A, B, C, D) or restate the choice text.
  NEVER use zero-based indices like "Option 0" — the learner sees lettered options.
- Avoid near-duplicates of the same wording, examples, or distractors.

EXCERPT:
\"\"\"{text[:14000]}\"\"\""""


def parse_questions(raw: str) -> list[ProviderQuestion]:
    """Parse and validate provider JSON output.

    LLM JSON is unreliable for long outputs (an unescaped quote in one string can
    invalidate the whole array), so parsing is tolerant: it first tries the whole
    array, then falls back to recovering individual question objects so one bad
    item does not discard the rest.
    """

    text = _strip_code_fences(raw)
    data = _load_question_array(text)

    questions: list[ProviderQuestion] = []
    for item in data:
        parsed = _parse_question_item(item)
        if parsed is not None:
            questions.append(parsed)
    if not questions:
        raise ProviderError("Provider returned no valid questions.")
    return questions


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
    return raw


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _load_question_array(text: str) -> list[Any]:
    """Return a list of raw question dicts, tolerating minor JSON corruption."""

    start = text.find("[")
    end = text.rfind("]")
    candidate = text[start : end + 1] if start != -1 and end != -1 else text

    for attempt in (candidate, _remove_trailing_commas(candidate)):
        try:
            data = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]

    # Fallback: recover whatever balanced {...} objects we can and parse each
    # independently, skipping only the malformed ones.
    recovered: list[Any] = []
    for obj_text in _extract_json_objects(candidate):
        for attempt in (obj_text, _remove_trailing_commas(obj_text)):
            try:
                recovered.append(json.loads(attempt))
                break
            except json.JSONDecodeError:
                continue
    if recovered:
        return recovered

    try:
        json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Provider returned invalid JSON: {exc}") from exc
    raise ProviderError("Provider returned JSON, but not a question array.")


def _extract_json_objects(text: str) -> list[str]:
    """Extract top-level {...} object substrings, respecting JSON string escaping."""

    objects: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start : index + 1])
                    start = None
    return objects


def _parse_question_item(item: Any) -> ProviderQuestion | None:
    if not isinstance(item, dict):
        return None
    question_type = str(item.get("question_type") or "single_mcq")
    if question_type not in QUESTION_TYPES:
        question_type = "single_mcq"
    prompt = str(item.get("prompt") or item.get("question") or "").strip()
    if not prompt:
        return None
    options = item.get("options") or []
    if not isinstance(options, list):
        options = []
    options = [str(option) for option in options]
    answer = item.get("answer")
    if answer is None and "answer_index" in item:
        answer = {"index": item.get("answer_index")}
    if not isinstance(answer, dict):
        answer = {"text": str(answer or "")}

    if question_type in {"single_mcq", "applied_scenario"} and options:
        index = answer.get("index")
        if not isinstance(index, int) or not 0 <= index < len(options):
            return None
        if len(options) != 4:
            return None
    if question_type == "multi_select":
        indices = answer.get("indices")
        if not isinstance(indices, list) or not all(isinstance(i, int) and 0 <= i < len(options) for i in indices):
            return None
        if len(set(indices)) < 2:
            return None
    if question_type in {"cloze", "spot_error", "short_answer", "compare_contrast"}:
        if not str(answer.get("text", "")).strip():
            return None

    return ProviderQuestion(
        concept_title=str(item.get("concept_title") or "Untitled concept").strip(),
        concept_summary=str(item.get("concept_summary") or "").strip(),
        topic_slug=str(item.get("topic_slug") or "general").strip().lower() or "general",
        question_type=question_type,
        prompt=prompt,
        options=options,
        answer=answer,
        explanation=str(item.get("explanation") or "").strip(),
        bloom=str(item.get("bloom") or "apply").strip().lower(),
    )
