from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.services.llm_client import LLMClientResult


DEFAULT_FAKE_PAYLOAD: dict[str, Any] = {
    "intent": "clarify",
    "confidence": 0.9,
    "actions": [],
    "needs_clarification": True,
    "clarification_question": "请明确你想点菜、看菜单还是修改订单。",
}


class DisabledLLMClient:
    runtime_mode = "disabled"
    timeout_seconds = 0.0
    top_candidates = 8
    min_confidence = 0.65
    speculative_enabled = False
    network_allowed = False
    is_shadow = False

    def __init__(self, *, config_error: str | None = None) -> None:
        self.config_error = config_error

    def is_enabled(self) -> bool:
        return False

    def is_configured(self) -> bool:
        return False

    def can_call(self) -> bool:
        return False

    def interpret(self, *_args: Any, **_kwargs: Any) -> LLMClientResult:
        return LLMClientResult(status=self.config_error or "disabled")


class InMemoryFakeLLMClient:
    runtime_mode = "fake"
    timeout_seconds = 0.0
    top_candidates = 8
    min_confidence = 0.65
    speculative_enabled = False
    network_allowed = False
    is_shadow = False

    def __init__(self, response: dict[str, Any] | LLMClientResult | None = None) -> None:
        self.response = response if response is not None else DEFAULT_FAKE_PAYLOAD
        self.calls: list[dict[str, str]] = []

    def is_enabled(self) -> bool:
        return True

    def is_configured(self) -> bool:
        return True

    def can_call(self) -> bool:
        return True

    def interpret(self, message: str, *, prompt: str | None = None, system_prompt: str | None = None) -> LLMClientResult:
        # Keep only already-sanitized prompt material; never retain the raw user message.
        self.calls.append({"prompt": prompt or "", "system_prompt": system_prompt or ""})
        if isinstance(self.response, LLMClientResult):
            return self.response
        return LLMClientResult(status="success", payload=self.response, parse_ok=True, latency_ms=0)


class ReplayLLMClient:
    runtime_mode = "replay"
    timeout_seconds = 0.0
    top_candidates = 8
    min_confidence = 0.65
    speculative_enabled = False
    network_allowed = False
    is_shadow = False

    def __init__(self, replay_file: str | Path | None) -> None:
        self.replay_file = Path(replay_file).resolve() if replay_file else None
        self.calls = 0

    def is_enabled(self) -> bool:
        return True

    def is_configured(self) -> bool:
        return self.replay_file is not None

    def can_call(self) -> bool:
        return self.is_configured()

    def interpret(self, *_args: Any, **_kwargs: Any) -> LLMClientResult:
        self.calls += 1
        started = time.perf_counter()
        if self.replay_file is None:
            return LLMClientResult(status="missing_replay_file", latency_ms=0)
        if self.replay_file.suffix.lower() != ".json" or self.replay_file.name.startswith("."):
            return LLMClientResult(status="unsafe_replay_path", latency_ms=0)
        try:
            if self.replay_file.stat().st_size > 256 * 1024:
                return LLMClientResult(status="replay_file_too_large", latency_ms=_elapsed_ms(started))
            document = json.loads(self.replay_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return LLMClientResult(status="replay_file_not_found", latency_ms=_elapsed_ms(started))
        except (OSError, json.JSONDecodeError):
            return LLMClientResult(status="malformed_replay", latency_ms=_elapsed_ms(started), parse_ok=False)
        if not isinstance(document, dict):
            return LLMClientResult(status="malformed_replay", latency_ms=_elapsed_ms(started), parse_ok=False)

        if "status" in document:
            status = str(document.get("status") or "malformed_replay")
            payload = document.get("payload")
            return LLMClientResult(
                status=status,
                payload=payload if isinstance(payload, dict) else None,
                latency_ms=int(document.get("latency_ms") or _elapsed_ms(started)),
                timed_out=bool(document.get("timed_out", status == "timeout")),
                parse_ok=bool(document.get("parse_ok", status == "success" and isinstance(payload, dict))),
            )
        return LLMClientResult(status="success", payload=document, latency_ms=_elapsed_ms(started), parse_ok=True)


class ShadowLLMClient:
    runtime_mode = "shadow"
    network_allowed = False
    is_shadow = True

    def __init__(self, source: InMemoryFakeLLMClient | ReplayLLMClient) -> None:
        self.source = source
        self.sandbox_source = source.runtime_mode
        self.timeout_seconds = source.timeout_seconds
        self.top_candidates = source.top_candidates
        self.min_confidence = source.min_confidence
        self.speculative_enabled = False

    def is_enabled(self) -> bool:
        return self.source.is_enabled()

    def is_configured(self) -> bool:
        return self.source.is_configured()

    def can_call(self) -> bool:
        return self.source.can_call()

    def interpret(self, *args: Any, **kwargs: Any) -> LLMClientResult:
        return self.source.interpret(*args, **kwargs)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
