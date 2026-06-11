from __future__ import annotations

from app.state.session_state import SessionState


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState()
        return self._sessions[session_id]

    def set(self, session_id: str, state: SessionState) -> None:
        self._sessions[session_id] = state

    def reset(self, session_id: str) -> SessionState:
        state = SessionState()
        self._sessions[session_id] = state
        return state

