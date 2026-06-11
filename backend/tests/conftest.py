import pytest

from app.agents.orchestrator import OrchestratorAgent
from app.state.session_state import SessionState


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

