"""Configuration helpers for local-first Ultralearn runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "ultralearn.db"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration selected from environment variables and UI settings."""

    db_path: Path = DEFAULT_DB_PATH
    provider: str = "claude_code"
    model: str = "claude-sonnet-4-6"
    claude_command: str = "claude"
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "llama3.1"
    provider_timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            db_path=Path(os.environ.get("ULTRALEARN_DB", DEFAULT_DB_PATH)),
            provider=os.environ.get("ULTRALEARN_PROVIDER", "claude_code"),
            model=os.environ.get("ULTRALEARN_MODEL", "claude-sonnet-4-6"),
            claude_command=os.environ.get("CLAUDE_CODE_COMMAND", "claude"),
            ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1"),
            provider_timeout_seconds=int(os.environ.get("ULTRALEARN_PROVIDER_TIMEOUT", "300")),
        )
