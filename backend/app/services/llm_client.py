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
        self.enabled = _bool_value("LLM_FALLBACK_ENABLED", False)
        self.provider = _config_value("LLM_FALLBACK_PROVIDER", "deepseek") or "deepseek"
        self.api_key = _fallback_config_value("LLM_FALLBACK_API_KEY", "DEEPSEEK_API_KEY")
        self.base_url = _fallback_config_value("LLM_FALLBACK_BASE_URL", "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = _fallback_config_value("LLM_FALLBACK_MODEL", "DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout_seconds = _float_value("LLM_FALLBACK_TIMEOUT_SECONDS", 2.5)
        self.max_tokens = _int_value("LLM_FALLBACK_MAX_TOKENS", 180)
        self.temperature = _float_value("LLM_FALLBACK_TEMPERATURE", 0)
        self.top_candidates = _int_value("LLM_FALLBACK_TOP_CANDIDATES", 8)
        self.min_confidence = _float_value("LLM_FALLBACK_MIN_CONFIDENCE", 0.65)
        self.speculative_enabled = _bool_value("LLM_FALLBACK_SPECULATIVE_ENABLED", False)
        self._http_client = http_client

    def is_enabled(self) -> bool:
        return self.enabled

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def can_call(self) -> bool:
        return self.is_enabled() and self.is_configured()

    def interpret(self, message: str, *, prompt: str | None = None, system_prompt: str | None = None) -> LLMClientResult:
        if not self.is_enabled():
            return LLMClientResult(status="disabled")
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
