from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv


class LLMClient:
    def __init__(self) -> None:
        load_dotenv()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def interpret(self, message: str) -> dict[str, Any] | None:
        if not self.is_configured():
            return None
        # The deterministic router owns required semantics during development.
        # A real DeepSeek request can be added here without changing agent contracts.
        return None
