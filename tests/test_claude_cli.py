"""Tests for how the Claude Code CLI is invoked and its output interpreted.

These cover the failure modes that made generation unreliable in practice:
malformed JSON from unconstrained output, and an expired login that surfaces as
a multi-minute hang rather than an error.
"""

import json

import pytest

from ultralearn import providers
from ultralearn.providers import (
    DENIED_TOOLS,
    ClaudeCodeProvider,
    ProviderAuthError,
    ProviderError,
)


@pytest.fixture
def modern_cli(monkeypatch):
    """A CLI supporting every flag Ultralearn knows about."""

    flags = frozenset(
        {
            "--json-schema",
            "--strict-mcp-config",
            "--mcp-config",
            "--setting-sources",
            "--fallback-model",
            "--disallowedTools",
            "--model",
        }
    )
    monkeypatch.setattr(providers, "claude_cli_flags", lambda executable: flags)
    return flags


@pytest.fixture
def legacy_cli(monkeypatch):
    """An older CLI with no schema or isolation support."""

    monkeypatch.setattr(providers, "claude_cli_flags", lambda executable: frozenset())


def test_command_is_isolated_and_schema_constrained(modern_cli):
    provider = ClaudeCodeProvider(model="sonnet", fallback_model="haiku")
    cmd = provider._build_command(schema={"type": "object"})

    assert cmd[:2] == ["claude", "-p"]
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "sonnet"
    assert "--fallback-model" in cmd and cmd[cmd.index("--fallback-model") + 1] == "haiku"
    assert "--strict-mcp-config" in cmd
    assert "--disallowedTools" in cmd and cmd[cmd.index("--disallowedTools") + 1] == DENIED_TOOLS
    assert "--json-schema" in cmd


def test_empty_mcp_config_keeps_the_shape_the_cli_validates(modern_cli):
    """`{}` is rejected by the CLI; it insists on an `mcpServers` map."""

    cmd = ClaudeCodeProvider()._build_command(schema=None)
    payload = json.loads(cmd[cmd.index("--mcp-config") + 1])
    assert payload == {"mcpServers": {}}


def test_unsupported_flags_are_omitted_rather_than_failing(legacy_cli):
    cmd = ClaudeCodeProvider(model="sonnet", fallback_model="haiku")._build_command(
        schema={"type": "object"}
    )
    assert cmd == ["claude", "-p", "--output-format", "json"]


def test_isolation_can_be_dropped_for_the_degraded_retry(modern_cli):
    cmd = ClaudeCodeProvider()._build_command(schema=None, isolated=False)
    assert "--strict-mcp-config" not in cmd
    assert "--disallowedTools" not in cmd


def test_custom_command_with_prompt_placeholder_is_left_alone(modern_cli):
    provider = ClaudeCodeProvider(command="my-wrapper --ask {prompt}")
    assert provider._build_command(schema=None) == ["my-wrapper", "--ask", "{prompt}"]


def test_structured_output_is_preferred_over_free_text():
    """The whole point of --json-schema: no string parsing of model prose."""

    provider = ClaudeCodeProvider()
    envelope = json.dumps(
        {
            "type": "result",
            "result": "here are your questions, hope this helps!",
            "structured_output": {"questions": [{"prompt": "What breaks first?"}]},
        }
    )
    assert json.loads(provider._extract_result(envelope)) == [{"prompt": "What breaks first?"}]


def test_expired_login_is_reported_as_an_auth_error():
    provider = ClaudeCodeProvider()
    envelope = json.dumps(
        {
            "type": "result",
            "is_error": True,
            "result": 'API Error: 401 {"type":"error","error":{"type":"authentication_error",'
            '"message":"OAuth access token has expired. Re-authenticate to continue."}} '
            "· Please run /login",
        }
    )
    with pytest.raises(ProviderAuthError, match="/login"):
        provider._extract_result(envelope)


def test_auth_failure_is_cached_so_later_calls_fail_fast():
    provider = ClaudeCodeProvider()
    envelope = json.dumps(
        {"type": "result", "is_error": True, "result": "Please run /login"}
    )
    with pytest.raises(ProviderAuthError):
        provider._extract_result(envelope)
    # A cached unhealthy result short-circuits before spawning a subprocess.
    assert provider.check_auth() == (False, providers._AUTH_HELP)
    with pytest.raises(ProviderAuthError):
        provider._complete("anything")


def test_non_auth_errors_stay_generic():
    provider = ClaudeCodeProvider()
    envelope = json.dumps({"type": "result", "is_error": True, "result": "usage limit reached"})
    with pytest.raises(ProviderError) as excinfo:
        provider._extract_result(envelope)
    assert not isinstance(excinfo.value, ProviderAuthError)


def test_slow_health_check_is_read_as_a_login_problem(monkeypatch):
    import subprocess

    def explode(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=25)

    monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/local/bin/claude")
    monkeypatch.setattr(providers.subprocess, "run", explode)

    healthy, message = ClaudeCodeProvider().check_auth(timeout_seconds=25)
    assert healthy is False
    assert "/login" in message


def test_generation_requests_the_question_schema(monkeypatch):
    provider = ClaudeCodeProvider()
    seen: dict = {}

    def fake_complete(prompt, schema=None):
        seen["schema"] = schema
        return json.dumps(
            [
                {
                    "concept_title": "Backprop",
                    "question_type": "short_answer",
                    "prompt": "Why does the gradient vanish here?",
                    "answer": {"text": "saturating activations"},
                    "explanation": "chain rule shrinks the product",
                    "bloom": "analyze",
                }
            ]
        )

    monkeypatch.setattr(provider, "_complete", fake_complete)
    questions = provider.generate_questions("notes", n=1, topic_slug="dl")

    assert len(questions) == 1
    assert seen["schema"] is providers.QUESTION_BATCH_SCHEMA
