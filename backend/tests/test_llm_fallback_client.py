from __future__ import annotations

import pytest

from app.services import llm_client as llm_module
from app.services.llm_client import LLMClient


class NetworkBlocker:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("network must not be called")


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": '{"intent":"ask_menu","confidence":0.9,"actions":[]}'}}]}


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse()


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("BACKEND_ENV_FILE", str(env_file))
    for name in [
        "LLM_FALLBACK_ENABLED",
        "LLM_FALLBACK_API_KEY",
        "LLM_FALLBACK_BASE_URL",
        "LLM_FALLBACK_MODEL",
        "LLM_FALLBACK_TIMEOUT_SECONDS",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)
    llm_module._env_file_values.cache_clear()
    yield
    llm_module._env_file_values.cache_clear()


def test_config_semantics_distinguish_enabled_configured_and_can_call(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "test-placeholder-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "deepseek-chat")

    client = LLMClient(http_client=NetworkBlocker())

    assert client.is_enabled() is False
    assert client.is_configured() is True
    assert client.can_call() is False


def test_disabled_fallback_does_not_call_network(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "test-placeholder-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "deepseek-chat")
    blocker = NetworkBlocker()

    result = LLMClient(http_client=blocker).interpret("随便处理一下")

    assert result.status == "disabled"
    assert blocker.calls == 0


def test_missing_key_does_not_call_network(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "deepseek-chat")
    blocker = NetworkBlocker()
    client = LLMClient(http_client=blocker)

    result = client.interpret("随便处理一下")

    assert client.is_enabled() is True
    assert client.is_configured() is False
    assert client.can_call() is False
    assert result.status == "missing_config"
    assert blocker.calls == 0


def test_successful_client_call_parses_short_json(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "test-placeholder-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "deepseek-chat")
    fake_http = FakeHttpClient()

    result = LLMClient(http_client=fake_http).interpret("看菜单", prompt="{}", system_prompt="json only")

    assert result.ok is True
    assert result.payload["intent"] == "ask_menu"
    assert result.parse_ok is True
    assert len(fake_http.calls) == 1


def test_successful_http_response_after_total_budget_is_timeout(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "test-placeholder-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_FALLBACK_TIMEOUT_SECONDS", "2.5")
    fake_http = FakeHttpClient()
    ticks = iter([100.0, 103.0])
    monkeypatch.setattr(llm_module.time, "perf_counter", lambda: next(ticks))

    result = LLMClient(http_client=fake_http).interpret("看菜单", prompt="{}", system_prompt="json only")

    assert result.status == "timeout"
    assert result.timed_out is True
    assert result.latency_ms == 3000
    assert result.payload is None
    assert len(fake_http.calls) == 1
