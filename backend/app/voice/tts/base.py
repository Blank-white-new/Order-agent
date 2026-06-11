from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class TTSProvider(ABC):
    def set_event_callback(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        """Optional hook used by the TTS runner for per-job diagnostics."""
        return None

    @abstractmethod
    def speak(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_speaking(self) -> bool:
        raise NotImplementedError

    def current_voice(self) -> dict[str, Any]:
        return {"id": None, "name": "default", "languages": []}
