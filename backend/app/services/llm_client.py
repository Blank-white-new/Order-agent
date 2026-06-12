from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


@lru_cache(maxsize=1)
def _env_file_values() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    values = dotenv_values(env_path) if env_path.exists() else {}
    return {key: str(value) for key, value in values.items() if value not in (None, "")}


def _config_value(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    return _env_file_values().get(name, default)


class LLMClient:
    def __init__(self) -> None:
        self.api_key = _config_value("DEEPSEEK_API_KEY")
        self.base_url = _config_value("DEEPSEEK_BASE_URL")
        self.model = _config_value("DEEPSEEK_MODEL", "deepseek-v4-pro")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def interpret(self, message: str) -> dict[str, Any] | None:
        if not self.is_configured():
            return None
        # The deterministic router owns required semantics during development.
        # A real DeepSeek request can be added here without changing agent contracts.
        return None
