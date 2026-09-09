from types import SimpleNamespace
import os
import sys
import types

from ultralearn.config import AppConfig
from ultralearn.providers import CursorProvider, ProviderAuthError, build_provider


def test_cursor_provider_is_unavailable_without_a_key(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    provider = CursorProvider(api_key="")
    assert provider.available() is False
    ready, message = provider.check_auth()
    assert ready is False
    assert "CURSOR_API_KEY" in message


def test_cursor_complete_disables_tools_and_uses_scratch(monkeypatch):
    seen: dict = {}

    def fake_prompt(prompt, options):
        seen["prompt"] = prompt
        seen["tools"] = options.tools
        seen["cwd"] = options.local.cwd
        seen["model"] = options.model
        seen["api_key"] = options.api_key
        return SimpleNamespace(status="finished", result='{"questions":[]}', usage=None)

    class FakeOptions:
        def __init__(self, **kwargs):
            self.tools = kwargs.get("tools")
            self.local = kwargs.get("local")
            self.model = kwargs.get("model")
            self.api_key = kwargs.get("api_key")

    class FakeLocal:
        def __init__(self, cwd):
            self.cwd = cwd

    fake_mod = types.ModuleType("cursor_sdk")
    fake_mod.Agent = SimpleNamespace(prompt=fake_prompt)
    fake_mod.AgentOptions = FakeOptions
    fake_mod.LocalAgentOptions = FakeLocal
    fake_mod.CursorAgentError = type("CursorAgentError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "cursor_sdk", fake_mod)

    provider = CursorProvider(model="grok-4.6", api_key="cursor_test")
    text = provider._complete("name the concepts", schema={"type": "object"})
    assert '"questions"' in text
    assert seen["tools"] == []
    assert seen["model"] == "grok-4.6"
    assert seen["api_key"] == "cursor_test"
    assert "ultralearn-cursor-scratch" in seen["cwd"]
    assert "ONLY valid JSON" in seen["prompt"]


def test_cursor_complete_without_a_key_is_an_auth_error(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    provider = CursorProvider(api_key="")
    try:
        provider._complete("hello")
        raise AssertionError("expected ProviderAuthError")
    except ProviderAuthError as exc:
        assert "CURSOR_API_KEY" in str(exc)


def test_build_provider_selects_cursor():
    provider = build_provider(
        "cursor",
        AppConfig(),
        cursor_key="cursor_test",
        cursor_model="grok-4.6",
    )
    assert provider.name == "cursor"
    assert provider.model == "grok-4.6"


def test_local_env_file_is_loaded_and_persisted(tmp_path, monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    env_path = tmp_path / "env"
    monkeypatch.setattr("ultralearn.config.LOCAL_ENV_PATH", env_path)

    from ultralearn.config import load_local_env, local_secret_configured, persist_local_secret

    persist_local_secret("CURSOR_API_KEY", "cursor_from_file")
    assert env_path.stat().st_mode & 0o777 == 0o600
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    assert local_secret_configured("CURSOR_API_KEY")
    load_local_env()
    assert os.environ["CURSOR_API_KEY"] == "cursor_from_file"


def test_from_env_defaults_to_cursor_when_a_key_is_saved(tmp_path, monkeypatch):
    monkeypatch.delenv("ULTRALEARN_PROVIDER", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr("ultralearn.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("ultralearn.config.LOCAL_ENV_PATH", tmp_path / "env")

    from ultralearn.config import persist_local_secret

    persist_local_secret("CURSOR_API_KEY", "cursor_from_file")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    config = AppConfig.from_env()
    assert config.provider == "cursor"
    assert config.cursor_model == "grok-4.6"
    os.environ.pop("CURSOR_API_KEY", None)
