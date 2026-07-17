import os
import tempfile
import uuid
from pathlib import Path

import pytest


_LLM_CONNECTION_ENV_VARS = (
    "LLM_FALLBACK_API_KEY",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "LLM_FALLBACK_REPLAY_FILE",
    "LLM_FALLBACK_SHADOW_SOURCE",
)
_OFFLINE_ENV_FILE = str(
    Path(tempfile.gettempdir()) / f"agent-order-pytest-offline-{os.getpid()}-{uuid.uuid4().hex}.env"
)


def _force_offline_llm_environment() -> None:
    """Keep normal pytest collection and execution isolated from live LLM config."""
    os.environ["LLM_FALLBACK_MODE"] = "disabled"
    os.environ["LLM_FALLBACK_ENABLED"] = "false"
    os.environ["LLM_FALLBACK_SPECULATIVE_ENABLED"] = "false"
    os.environ["ALLOW_LIVE_LLM"] = "false"
    os.environ["VOICE_ENABLED"] = "false"
    os.environ["TTS_ENABLED"] = "false"
    os.environ["SIMULATION_DATA_ONLY"] = "true"
    os.environ["BACKEND_ENV_FILE"] = _OFFLINE_ENV_FILE
    for name in _LLM_CONNECTION_ENV_VARS:
        os.environ.pop(name, None)


# Run before importing application modules so module-level clients cannot read the project .env.
_force_offline_llm_environment()

from app.agents.orchestrator import OrchestratorAgent
from app.services import llm_client as llm_module
from app.state.session_state import SessionState


@pytest.fixture(autouse=True)
def force_offline_llm_for_tests(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODE", "disabled")
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("LLM_FALLBACK_SPECULATIVE_ENABLED", "false")
    monkeypatch.setenv("ALLOW_LIVE_LLM", "false")
    monkeypatch.setenv("VOICE_ENABLED", "false")
    monkeypatch.setenv("TTS_ENABLED", "false")
    monkeypatch.setenv("SIMULATION_DATA_ONLY", "true")
    monkeypatch.setenv("BACKEND_ENV_FILE", _OFFLINE_ENV_FILE)
    for name in _LLM_CONNECTION_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    llm_module._env_file_values.cache_clear()
    yield
    llm_module._env_file_values.cache_clear()


@pytest.fixture
def orchestrator():
    return OrchestratorAgent()


@pytest.fixture
def fresh_state():
    return SessionState()


def send(orchestrator, message, state=None):
    state = state or SessionState()
    return orchestrator.handle_user_message(message, state)


def assert_trace_basics(result, *, agent, handler, intent, fallback=False):
    trace = result["trace"]
    assert trace["selectedAgent"] == agent
    assert trace["selectedHandler"] == handler
    assert trace["finalIntent"] == intent
    assert trace["fallbackUsed"] is fallback
    assert trace["interpretationSource"] in {"rule", "deterministic", "merged", "llm"}
    assert isinstance(result["response"], str)
    assert result["response"]


def assert_no_order_mutation(result):
    trace = result["trace"]
    assert trace["orderBefore"] == trace["orderAfter"]
    assert trace["officialAddressBefore"] == trace["officialAddressAfter"]
    assert result["state"]["phone"] is None

