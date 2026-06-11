from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.agents.orchestrator import OrchestratorAgent
from app.state.session_store import InMemorySessionStore


@dataclass
class _LockRecord:
    lock: asyncio.Lock
    last_seen: float


class SessionLockManager:
    def __init__(self, ttl_seconds: int = 600, max_locks: int = 512) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_locks = max_locks
        self._records: OrderedDict[str, _LockRecord] = OrderedDict()

    def get_lock(self, session_id: str) -> asyncio.Lock:
        now = time.monotonic()
        self._cleanup(now)
        record = self._records.get(session_id)
        if not record:
            record = _LockRecord(lock=asyncio.Lock(), last_seen=now)
            self._records[session_id] = record
        record.last_seen = now
        self._records.move_to_end(session_id)
        return record.lock

    def _cleanup(self, now: float | None = None) -> None:
        now = now or time.monotonic()
        expired = [
            session_id
            for session_id, record in self._records.items()
            if not record.lock.locked() and now - record.last_seen > self.ttl_seconds
        ]
        for session_id in expired:
            self._records.pop(session_id, None)
        while len(self._records) > self.max_locks:
            session_id, record = next(iter(self._records.items()))
            if record.lock.locked():
                break
            self._records.pop(session_id, None)


class TextEntryService:
    def __init__(
        self,
        store: InMemorySessionStore,
        orchestrator: OrchestratorAgent,
        lock_manager: SessionLockManager | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.lock_manager = lock_manager or SessionLockManager()

    async def handle_text_message(self, session_id: str, text: str) -> dict[str, Any]:
        lock = self.lock_manager.get_lock(session_id)
        async with lock:
            return await asyncio.to_thread(self._handle_text_message_sync, session_id, text)

    def _handle_text_message_sync(self, session_id: str, text: str) -> dict[str, Any]:
        state = self.store.get(session_id)
        result = self.orchestrator.handle_user_message(text, state)
        self.store.set(session_id, result["raw_state"])
        return {
            "session_id": session_id,
            "response": result["response"],
            "state": result["state"],
            "trace": result["trace"],
            "raw_state": result["raw_state"],
        }
