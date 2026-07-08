from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from app.services.llm_fallback_modes import (
    LLMRuntimeMode,
    describe_llm_runtime_safety,
    parse_llm_fallback_mode,
)


TRUE_VALUES = {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _env_file_values() -> dict[str, str]:
    configured = os.getenv("BACKEND_ENV_FILE")
    if configured:
        env_path = Path(configured)
        if not env_path.is_absolute():
            env_path = Path.cwd() / env_path
        env_path = env_path.resolve()
    else:
        env_path = Path(__file__).resolve().parents[3] / ".env"
    values = dotenv_values(env_path) if env_path.exists() else {}
    return {key: str(value) for key, value in values.items() if value not in (None, "")}


def _config_value(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    return _env_file_values().get(name, default)


def _fallback_config_value(name: str, legacy_name: str | None = None, default: str | None = None) -> str | None:
    value = _config_value(name)
    if value not in (None, ""):
        return value
    if legacy_name:
        legacy = _config_value(legacy_name)
        if legacy not in (None, ""):
            return legacy
    return default


def _bool_value(name: str, default: bool = False) -> bool:
    value = _config_value(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _float_value(name: str, default: float) -> float:
    value = _config_value(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_value(name: str, default: int) -> int:
    value = _config_value(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class LLMClientResult:
    status: str
    payload: dict[str, Any] | None = None
    raw_text: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    timed_out: bool = False
    parse_ok: bool = False
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success" and self.payload is not None


class LLMClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        # Mode is process-environment only so disabled/sandbox startup never parses a dotenv file.
        self.mode, self.config_error = parse_llm_fallback_mode(os.getenv("LLM_FALLBACK_MODE", "disabled"))
        self.enabled = (os.getenv("LLM_FALLBACK_ENABLED") or "").strip().lower() in TRUE_VALUES
        self.allow_live = (os.getenv("ALLOW_LIVE_LLM") or "").strip().lower() in TRUE_VALUES
        self.runtime_mode = self.mode.value
        self.network_allowed = self.mode is LLMRuntimeMode.LIVE and self.enabled and self.allow_live
        self.is_shadow = False
        # Provider secrets are not read at all unless the explicit live mode is selected.
        if self.mode is LLMRuntimeMode.LIVE:
            self.provider = _config_value("LLM_FALLBACK_PROVIDER", "deepseek") or "deepseek"
            self.api_key = _fallback_config_value("LLM_FALLBACK_API_KEY", "DEEPSEEK_API_KEY")
            self.base_url = _fallback_config_value(
                "LLM_FALLBACK_BASE_URL", "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
            )
            self.model = _fallback_config_value("LLM_FALLBACK_MODEL", "DEEPSEEK_MODEL", "deepseek-chat")
        else:
            self.provider = None
            self.api_key = None
            self.base_url = None
            self.model = None
        if self.mode is LLMRuntimeMode.LIVE:
            self.timeout_seconds = _float_value("LLM_FALLBACK_TIMEOUT_SECONDS", 2.5)
            self.max_tokens = _int_value("LLM_FALLBACK_MAX_TOKENS", 180)
            self.temperature = _float_value("LLM_FALLBACK_TEMPERATURE", 0)
            self.top_candidates = _int_value("LLM_FALLBACK_TOP_CANDIDATES", 8)
            self.min_confidence = _float_value("LLM_FALLBACK_MIN_CONFIDENCE", 0.65)
            self.speculative_enabled = _bool_value("LLM_FALLBACK_SPECULATIVE_ENABLED", False)
        else:
            self.timeout_seconds = 2.5
            self.max_tokens = 180
            self.temperature = 0.0
            self.top_candidates = 8
            self.min_confidence = 0.65
            self.speculative_enabled = False
        self._http_client = http_client

    def is_enabled(self) -> bool:
        return self.mode is LLMRuntimeMode.LIVE and self.enabled

    def is_configured(self) -> bool:
        return self.mode is LLMRuntimeMode.LIVE and bool(self.api_key and self.base_url and self.model)

    def can_call(self) -> bool:
        return self.network_allowed and self.is_configured() and self.config_error is None

    def describe_safety(self) -> dict[str, Any]:
        return describe_llm_runtime_safety(
            mode=self.mode,
            enabled=self.enabled,
            allow_live=self.allow_live,
            config_error=self.config_error,
        )

    def interpret(self, message: str, *, prompt: str | None = None, system_prompt: str | None = None) -> LLMClientResult:
        if self.config_error:
            return LLMClientResult(status="invalid_mode", error=self.config_error)
        if not self.is_enabled():
            return LLMClientResult(status="disabled")
        if not self.allow_live:
            return LLMClientResult(status="live_not_allowed")
        if not self.is_configured():
            return LLMClientResult(status="missing_config")

        started = time.perf_counter()
        try:
            response = self._post_chat_completion(prompt or message, system_prompt=system_prompt)
        except httpx.TimeoutException:
            return LLMClientResult(status="timeout", latency_ms=self._elapsed_ms(started), timed_out=True)
        except httpx.HTTPError as exc:
            return LLMClientResult(status="network_error", error=type(exc).__name__, latency_ms=self._elapsed_ms(started))
        except Exception as exc:
            return LLMClientResult(status="network_error", error=type(exc).__name__, latency_ms=self._elapsed_ms(started))

        latency_ms = self._elapsed_ms(started)
        if self._timed_out_by_wall_clock(latency_ms):
            return LLMClientResult(status="timeout", latency_ms=latency_ms, timed_out=True)
        if response.status_code < 200 or response.status_code >= 300:
            return LLMClientResult(status="http_error", latency_ms=latency_ms, http_status=response.status_code)

        raw_text = self._extract_content(response)
        if not raw_text:
            return LLMClientResult(status="empty_response", latency_ms=latency_ms, parse_ok=False)

        try:
            payload = json.loads(self._strip_json_fences(raw_text))
        except json.JSONDecodeError:
            return LLMClientResult(status="invalid_json", raw_text=raw_text[:200], latency_ms=latency_ms, parse_ok=False)
        if not isinstance(payload, dict):
            return LLMClientResult(status="invalid_json", raw_text=raw_text[:200], latency_ms=latency_ms, parse_ok=False)
        return LLMClientResult(status="success", payload=payload, raw_text=raw_text[:200], latency_ms=latency_ms, parse_ok=True)

    def _post_chat_completion(self, prompt: str, *, system_prompt: str | None = None) -> httpx.Response:
        if not self.can_call():
            raise RuntimeError("live LLM call blocked by runtime safety policy")
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt or "You are an ordering intent parser. Return one JSON object only.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self._http_client is not None:
            return self._http_client.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.post(url, headers=headers, json=payload)

    def _extract_content(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text.strip()
        choices = body.get("choices") if isinstance(body, dict) else None
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"].strip()
                if isinstance(first.get("text"), str):
                    return first["text"].strip()
        return response.text.strip()

    def _strip_json_fences(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return stripped

    def _elapsed_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _timed_out_by_wall_clock(self, latency_ms: int) -> bool:
        return latency_ms > int(self.timeout_seconds * 1000)


def create_llm_fallback_client() -> Any:
    """Build a runtime client without ever turning an unknown mode into live access."""
    live_client = LLMClient()
    if live_client.config_error:
        from app.services.llm_replay_client import DisabledLLMClient

        return DisabledLLMClient(config_error=live_client.config_error)
    if live_client.mode is LLMRuntimeMode.DISABLED:
        from app.services.llm_replay_client import DisabledLLMClient

        return DisabledLLMClient()
    if live_client.mode is LLMRuntimeMode.LIVE:
        return live_client

    from app.services.llm_replay_client import InMemoryFakeLLMClient, ReplayLLMClient, ShadowLLMClient

    if live_client.mode is LLMRuntimeMode.FAKE:
        return InMemoryFakeLLMClient()
    replay_file = os.getenv("LLM_FALLBACK_REPLAY_FILE")
    if live_client.mode is LLMRuntimeMode.REPLAY:
        return ReplayLLMClient(replay_file)
    shadow_source = (os.getenv("LLM_FALLBACK_SHADOW_SOURCE") or "fake").strip().lower()
    source = ReplayLLMClient(replay_file) if shadow_source == "replay" else InMemoryFakeLLMClient()
    return ShadowLLMClient(source)
