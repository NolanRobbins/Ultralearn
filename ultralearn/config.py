"""Configuration helpers for local-first Ultralearn runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "ultralearn.db"
#: Machine-local secrets (CURSOR_API_KEY, etc.). Never stored in the repo.
LOCAL_ENV_PATH = Path.home() / ".config" / "ultralearn" / "env"


def load_dotenv_file(path: Path) -> None:
    """Load KEY=value lines into os.environ without overriding a live export."""

    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_local_env() -> None:
    load_dotenv_file(PROJECT_ROOT / ".env")
    load_dotenv_file(LOCAL_ENV_PATH)


def persist_local_secret(name: str, value: str) -> Path:
    """Write one secret into ~/.config/ultralearn/env (mode 600) and export it."""

    value = value.strip()
    LOCAL_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if LOCAL_ENV_PATH.is_file():
        existing = [
            line
            for line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines()
            if not line.startswith(f"{name}=")
        ]
    existing.append(f"{name}={value}")
    LOCAL_ENV_PATH.write_text("\n".join(existing) + "\n", encoding="utf-8")
    LOCAL_ENV_PATH.chmod(0o600)
    os.environ[name] = value
    return LOCAL_ENV_PATH


def local_secret_configured(name: str) -> bool:
    if os.environ.get(name, "").strip():
        return True
    if not LOCAL_ENV_PATH.is_file():
        return False
    try:
        for line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}=") and line.split("=", 1)[1].strip():
                return True
    except OSError:
        return False
    return False


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration selected from environment variables and UI settings."""

    db_path: Path = DEFAULT_DB_PATH
    provider: str = "claude_code"
    model: str = "claude-sonnet-4-6"
    claude_command: str = "claude"
    #: Model alias handed to the Claude Code CLI. Aliases like "sonnet" always
    #: resolve to the current release, whereas dated full names go stale and make
    #: the CLI fail outright, so this is kept separate from the API `model`.
    claude_model: str = "sonnet"
    #: Used only when the primary model is overloaded. Empty disables fallback.
    claude_fallback_model: str = ""
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "llama3.1"
    cursor_model: str = "grok-4.6"
    provider_timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_local_env()
        explicit_provider = os.environ.get("ULTRALEARN_PROVIDER", "").strip()
        if explicit_provider:
            provider = explicit_provider
        elif local_secret_configured("CURSOR_API_KEY"):
            provider = "cursor"
        else:
            provider = "claude_code"
        return cls(
            db_path=Path(os.environ.get("ULTRALEARN_DB", DEFAULT_DB_PATH)),
            provider=provider,
            model=os.environ.get("ULTRALEARN_MODEL", "claude-sonnet-4-6"),
            claude_command=os.environ.get("CLAUDE_CODE_COMMAND", "claude"),
            claude_model=os.environ.get("ULTRALEARN_CLAUDE_MODEL", "sonnet"),
            claude_fallback_model=os.environ.get("ULTRALEARN_CLAUDE_FALLBACK_MODEL", ""),
            ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1"),
            cursor_model=os.environ.get("ULTRALEARN_CURSOR_MODEL", "grok-4.6"),
            provider_timeout_seconds=int(os.environ.get("ULTRALEARN_PROVIDER_TIMEOUT", "300")),
        )
