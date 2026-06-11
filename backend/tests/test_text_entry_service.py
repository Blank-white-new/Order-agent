import asyncio
import time

from fastapi.testclient import TestClient

from app.main import app
from app.services.text_entry_service import TextEntryService
from app.state.session_state import SessionState


class FakeStore:
    def __init__(self) -> None:
        self.states: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        self.states.setdefault(session_id, SessionState())
        return self.states[session_id]

    def set(self, session_id: str, state: SessionState) -> None:
        self.states[session_id] = state


class SlowFakeOrchestrator:
    def __init__(self) -> None:
        self.active_by_session: dict[str, int] = {}
        self.max_active_by_session: dict[str, int] = {}
        self.calls: list[tuple[str, str]] = []

    def handle_user_message(self, message: str, state: SessionState) -> dict:
        session_id = state.pending_action["session_id"]
        self.calls.append((session_id, message))
        self.active_by_session[session_id] = self.active_by_session.get(session_id, 0) + 1
        self.max_active_by_session[session_id] = max(
            self.max_active_by_session.get(session_id, 0),
            self.active_by_session[session_id],
        )
        time.sleep(0.05)
        self.active_by_session[session_id] -= 1
        return {
            "response": f"ok:{message}",
            "state": state.serializable(),
            "trace": {"message": message},
            "raw_state": state,
        }


class SessionAwareStore(FakeStore):
    def get(self, session_id: str) -> SessionState:
        state = super().get(session_id)
        state.pending_action = {"session_id": session_id}
        return state


def test_chat_api_shape_stays_compatible():
    client = TestClient(app)

    response = client.post("/api/chat", json={"session_id": "api-compat", "message": "有啥"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"session_id", "response", "state", "trace"}
    assert body["session_id"] == "api-compat"
    assert body["trace"]["finalIntent"] == "ask_menu"
    assert "饭类" in body["response"]


def test_text_entry_service_serializes_same_session_messages():
    store = SessionAwareStore()
    orchestrator = SlowFakeOrchestrator()
    service = TextEntryService(store=store, orchestrator=orchestrator)

    async def run() -> None:
        await asyncio.gather(
            service.handle_text_message("same", "第一句"),
            service.handle_text_message("same", "第二句"),
        )

    asyncio.run(run())

    assert orchestrator.max_active_by_session["same"] == 1
    assert orchestrator.calls == [("same", "第一句"), ("same", "第二句")]


def test_text_entry_service_does_not_block_different_sessions():
    store = SessionAwareStore()
    orchestrator = SlowFakeOrchestrator()
    service = TextEntryService(store=store, orchestrator=orchestrator)

    async def run() -> float:
        start = time.perf_counter()
        await asyncio.gather(
            service.handle_text_message("a", "第一句"),
            service.handle_text_message("b", "第二句"),
        )
        return time.perf_counter() - start

    duration = asyncio.run(run())

    assert duration < 0.095
    assert orchestrator.max_active_by_session["a"] == 1
    assert orchestrator.max_active_by_session["b"] == 1
