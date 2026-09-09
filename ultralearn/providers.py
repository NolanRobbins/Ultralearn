"""Pluggable LLM providers for generation, critique, and coaching."""

from __future__ import annotations

import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
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

BLOOM_LEVELS = ["recall", "apply", "analyze"]

#: JSON Schema for a batch of generated questions. Handed to CLIs that support
#: schema-constrained output so the response is machine-valid by construction
#: instead of being hand-written JSON that has to survive string parsing.
QUESTION_BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept_title": {"type": "string"},
                    "concept_summary": {"type": "string"},
                    "topic_slug": {"type": "string"},
                    "question_type": {"type": "string", "enum": QUESTION_TYPES},
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "indices": {"type": "array", "items": {"type": "integer"}},
                            "text": {"type": "string"},
                        },
                    },
                    "explanation": {"type": "string"},
                    "bloom": {"type": "string", "enum": BLOOM_LEVELS},
                },
                "required": [
                    "concept_title",
                    "question_type",
                    "prompt",
                    "answer",
                    "explanation",
                    "bloom",
                ],
            },
        }
    },
    "required": ["questions"],
}


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete a requested LLM task."""


class ProviderAuthError(ProviderError):
    """Raised when a provider is installed and reachable but not logged in.

    Worth distinguishing: an expired Claude Code OAuth token still returns a
    success exit code, but only after the CLI has spent minutes retrying the 401
    internally. Surfacing it as its own error lets callers say "log in" instead
    of "something timed out".
    """


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
        return parse_questions(self._complete(prompt, schema=QUESTION_BATCH_SCHEMA))

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
    def _complete(self, prompt: str, schema: dict[str, Any] | None = None) -> str:
        """Run the provider-specific completion call.

        ``schema`` is an optional JSON Schema describing the expected response.
        Providers that can constrain output to a schema should use it; the rest
        ignore it and rely on the prompt plus tolerant parsing.
        """


#: Ultralearn only ever asks the CLI to write text, so every tool is denied. This
#: keeps a generation call from wandering into the filesystem or the network, and
#: removes an entire class of multi-turn stalls.
DENIED_TOOLS = (
    "Bash,Edit,Write,Read,WebFetch,WebSearch,Glob,Grep,Task,"
    "NotebookEdit,NotebookRead,MultiEdit,TodoWrite"
)

#: Substrings that mean "the CLI works but you are not logged in".
_AUTH_ERROR_MARKERS = (
    "oauth access token has expired",
    "please run /login",
    "authentication_error",
    "invalid api key",
    "invalid bearer token",
)

_USAGE_ERROR_MARKERS = (
    "unknown option",
    "unknown argument",
    "invalid mcp configuration",
    "error: option",
    "unknown command",
)


@functools.lru_cache(maxsize=8)
def claude_cli_flags(executable: str) -> frozenset[str]:
    """Return the subset of flags Ultralearn cares about that this CLI supports.

    Claude Code's flag surface moves between releases: ``--json-schema`` only
    exists from v2.1.205. Probing ``--help`` once lets a single code path serve
    old and new CLIs instead of hard-failing on whichever machine is older.
    """

    try:
        proc = subprocess.run(
            [executable, "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    help_text = f"{proc.stdout}\n{proc.stderr}"
    candidates = (
        "--json-schema",
        "--strict-mcp-config",
        "--mcp-config",
        "--setting-sources",
        "--fallback-model",
        "--disallowedTools",
        "--model",
        "--append-system-prompt",
    )
    return frozenset(flag for flag in candidates if flag in help_text)


@functools.lru_cache(maxsize=1)
def _scratch_dir() -> str:
    """An empty directory to run the CLI from.

    Claude Code reads ``CLAUDE.md`` and settings from its working directory, so
    running from the project would inject unrelated instructions into every
    study prompt. (User-level ``~/.claude/CLAUDE.md`` still loads; only ``--bare``
    suppresses that, and ``--bare`` also disables OAuth, which would force an API
    key and defeat the point of using the local CLI.)
    """

    path = Path(tempfile.gettempdir()) / "ultralearn-claude-scratch"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class ClaudeCodeProvider(PromptProvider):
    """Subprocess-backed provider driving the local Claude Code CLI.

    Every call is isolated: no MCP servers, no project settings, no tools, and a
    scratch working directory. The prompt goes in on stdin rather than argv so
    long excerpts are never subject to argument-length or quoting limits, and
    ``--output-format json`` gives back cost, token counts, and duration.
    """

    name = "claude_code"

    def __init__(
        self,
        command: str = "claude",
        timeout_seconds: int = 300,
        model: str = "sonnet",
        fallback_model: str = "",
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.fallback_model = fallback_model
        self._health: tuple[bool, str] | None = None

    @property
    def executable(self) -> str:
        parts = shlex.split(self.command) if self.command.strip() else []
        return parts[0] if parts else "claude"

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def check_auth(self, timeout_seconds: int = 8) -> tuple[bool, str]:
        """Cheaply establish whether the CLI is logged in.

        An expired token makes the CLI retry the 401 internally for minutes before
        returning, so without a bounded preflight every call looks like a timeout.
        The result is cached for the life of the provider.
        """

        if self._health is not None:
            return self._health
        if not self.available():
            self._health = (False, "Claude Code CLI was not found on PATH.")
            return self._health
        try:
            proc = subprocess.run(
                self._build_command(schema=None),
                input="Reply with exactly: OK",
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            # Almost always an expired token being retried behind the scenes.
            self._health = (
                False,
                "Claude Code did not respond within "
                f"{timeout_seconds}s. This usually means the login has expired — "
                "run `claude` in a terminal, then `/login`.",
            )
            return self._health
        except (OSError, subprocess.SubprocessError) as exc:
            self._health = (False, f"Claude Code could not be started: {exc}")
            return self._health

        combined = f"{proc.stdout}\n{proc.stderr}".lower()
        if any(marker in combined for marker in _AUTH_ERROR_MARKERS):
            self._health = (False, _AUTH_HELP)
            return self._health
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            self._health = (False, f"Claude Code failed: {detail[:300]}")
            return self._health
        self._health = (True, "Claude Code is ready.")
        return self._health

    def _build_command(self, schema: dict[str, Any] | None, isolated: bool = True) -> list[str]:
        """Assemble the CLI invocation, using only flags this CLI understands."""

        parts = shlex.split(self.command) if self.command.strip() else ["claude"]
        # A custom command containing {prompt} is honoured verbatim so power users
        # can wrap the CLI however they like.
        if any("{prompt}" in part for part in parts):
            return parts

        cmd = list(parts)
        if "-p" not in cmd and "--print" not in cmd:
            cmd.append("-p")
        if "--output-format" not in cmd:
            cmd += ["--output-format", "json"]

        flags = claude_cli_flags(self.executable)
        if self.model and "--model" in flags and "--model" not in cmd:
            cmd += ["--model", self.model]
        if self.fallback_model and "--fallback-model" in flags:
            cmd += ["--fallback-model", self.fallback_model]

        if isolated:
            if "--strict-mcp-config" in flags:
                cmd.append("--strict-mcp-config")
                if "--mcp-config" in flags:
                    # An empty server map, not `{}` — the CLI validates the shape.
                    cmd += ["--mcp-config", json.dumps({"mcpServers": {}})]
            if "--setting-sources" in flags:
                cmd += ["--setting-sources", ""]
            if "--disallowedTools" in flags:
                cmd += ["--disallowedTools", DENIED_TOOLS]

        if schema is not None and "--json-schema" in flags:
            cmd += ["--json-schema", json.dumps(schema)]
        return cmd

    def _complete(self, prompt: str, schema: dict[str, Any] | None = None) -> str:
        healthy, message = self.check_auth()
        if not healthy:
            raise ProviderAuthError(message)

        cmd = self._build_command(schema)
        legacy_prompt = any("{prompt}" in part for part in cmd)
        if legacy_prompt:
            cmd = [part.replace("{prompt}", prompt) for part in cmd]

        started = time.monotonic()
        proc = self._run(cmd, prompt if not legacy_prompt else None)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            # An unrecognised isolation flag should degrade, not break the app.
            if any(marker in detail.lower() for marker in _USAGE_ERROR_MARKERS):
                cmd = self._build_command(schema=None, isolated=False)
                proc = self._run(cmd, prompt)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                raise ProviderError(f"Claude Code failed: {detail[:800]}")
        return self._extract_result(proc.stdout, elapsed_seconds=time.monotonic() - started)

    def _run(self, cmd: list[str], stdin_prompt: str | None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                cmd,
                # The prompt arrives on stdin, so excerpt length is never bounded
                # by ARG_MAX and no shell quoting can corrupt it. When stdin is
                # not the prompt it must still be closed: in -p mode the CLI can
                # otherwise wait forever for interactive input.
                input=stdin_prompt if stdin_prompt is not None else "",
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=_scratch_dir(),
            )
        except FileNotFoundError as exc:
            raise ProviderError("Claude Code CLI was not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"Claude Code timed out after {self.timeout_seconds}s. Generation runs in small "
                "batches, so this usually means the CLI itself is stuck — check that `claude -p 'ok'` "
                "returns promptly in a terminal, or raise the provider timeout in Settings."
            ) from exc

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
            detail = str(envelope.get("result") or "")
            if any(marker in detail.lower() for marker in _AUTH_ERROR_MARKERS):
                self._health = (False, _AUTH_HELP)
                raise ProviderAuthError(_AUTH_HELP)
            raise ProviderError(f"Claude Code returned an error: {detail[:800]}")

        # With --json-schema the CLI returns a validated object; preferring it
        # removes the whole class of "model wrote slightly broken JSON" failures.
        structured = envelope.get("structured_output")
        if isinstance(structured, dict) and "questions" in structured:
            return json.dumps(structured["questions"])
        if isinstance(structured, list):
            return json.dumps(structured)
        return str(envelope.get("result") or "")


_AUTH_HELP = (
    "Claude Code is not logged in — its OAuth token has expired. Run `claude` in a "
    "terminal and use `/login`, then try again. (Ultralearn deliberately avoids "
    "`--bare`, which would bypass your subscription and require an API key.)"
)


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

    def _complete(self, prompt: str, schema: dict[str, Any] | None = None) -> str:
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

    def _complete(self, prompt: str, schema: dict[str, Any] | None = None) -> str:
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

    def _complete(self, prompt: str, schema: dict[str, Any] | None = None) -> str:
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"Ollama provider failed: {exc}") from exc
        return data.get("response", "")


_CURSOR_AUTH_HELP = (
    "Cursor needs a CURSOR_API_KEY. Create one at https://cursor.com/dashboard/integrations "
    "and export it in this shell. Logging into the Cursor IDE is not enough — the SDK cannot "
    "reuse that session."
)

_CURSOR_MODELS = (
    ("grok-4.6", "Grok 4.6"),
    ("composer-2.5", "Composer 2.5"),
    ("auto", "Auto"),
)
CURSOR_MODELS = _CURSOR_MODELS


@functools.lru_cache(maxsize=1)
def _cursor_scratch_dir() -> str:
    path = Path(tempfile.gettempdir()) / "ultralearn-cursor-scratch"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class CursorProvider(PromptProvider):
    """Cursor SDK provider: Grok, Composer, and Auto, billed to a Cursor API key.

    This is an agent runtime, not a raw chat-completions API. Tools are disabled
    so a generation or grading call can only return text — it must not edit the
    library or browse the web. The working directory is an empty scratch folder
    so project rules never leak into study prompts.
    """

    name = "cursor"

    def __init__(
        self,
        model: str = "grok-4.6",
        api_key: str | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.model = model or "grok-4.6"
        self.api_key = (api_key or os.environ.get("CURSOR_API_KEY") or "").strip()
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import cursor_sdk  # noqa: F401
        except Exception:
            return False
        return True

    def check_auth(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, _CURSOR_AUTH_HELP
        try:
            from cursor_sdk import Cursor
        except Exception:
            return False, "Install the cursor extra: uv sync --extra cursor"
        try:
            Cursor.me(api_key=self.api_key)
        except Exception as exc:
            return False, f"Cursor rejected the API key: {exc}"
        return True, f"Cursor is ready ({self.model})."

    def _complete(self, prompt: str, schema: dict[str, Any] | None = None) -> str:
        if not self.api_key:
            raise ProviderAuthError(_CURSOR_AUTH_HELP)
        try:
            from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
        except Exception as exc:
            raise ProviderError("Install the cursor extra: uv sync --extra cursor") from exc

        if schema is not None:
            prompt = (
                prompt
                + "\n\nReturn ONLY valid JSON matching the requested schema. "
                "No markdown fences and no prose."
            )

        try:
            result = Agent.prompt(
                prompt,
                AgentOptions(
                    api_key=self.api_key,
                    model=self.model,
                    tools=[],
                    local=LocalAgentOptions(cwd=_cursor_scratch_dir()),
                ),
            )
        except CursorAgentError as exc:
            message = str(exc)
            if any(marker in message.lower() for marker in _AUTH_ERROR_MARKERS):
                raise ProviderAuthError(_CURSOR_AUTH_HELP) from exc
            raise ProviderError(f"Cursor agent failed to start: {message[:800]}") from exc

        if getattr(result, "status", None) == "error":
            raise ProviderError("Cursor agent run failed.")
        text = str(getattr(result, "result", None) or "").strip()
        if not text:
            raise ProviderError("Cursor returned an empty response.")
        usage = getattr(result, "usage", None)
        self.last_usage = {
            "provider": self.name,
            "model": self.model,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        return text


def build_provider(
    name: str,
    config: AppConfig,
    anthropic_key: str = "",
    openai_key: str = "",
    cursor_key: str = "",
    cursor_model: str = "",
) -> Provider:
    normalized = (name or "claude_code").strip().lower()
    if normalized == "claude_code":
        return ClaudeCodeProvider(
            config.claude_command,
            config.provider_timeout_seconds,
            model=config.claude_model,
            fallback_model=config.claude_fallback_model,
        )
    if normalized == "anthropic":
        return AnthropicProvider(config.model, anthropic_key or None, config.provider_timeout_seconds)
    if normalized == "openai":
        return OpenAIProvider(config.model, openai_key or None, config.provider_timeout_seconds)
    if normalized == "cursor":
        return CursorProvider(
            model=cursor_model or config.cursor_model,
            api_key=cursor_key or None,
            timeout_seconds=config.provider_timeout_seconds,
        )
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
