from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from app.agents.orchestrator import OrchestratorAgent
from app.services.order_persistence_service import OrderPersistenceService
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
        store,
        orchestrator: OrchestratorAgent,
        lock_manager: SessionLockManager | None = None,
        orchestrator_factory: Callable[[str | None, str | None], OrchestratorAgent] | None = None,
        order_persistence_service: OrderPersistenceService | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.lock_manager = lock_manager or SessionLockManager()
        self.orchestrator_factory = orchestrator_factory
        self.order_persistence_service = order_persistence_service

    async def handle_text_message(
        self,
        session_id: str,
        text: str,
        *,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        lock = self.lock_manager.get_lock(session_id)
        async with lock:
            return await asyncio.to_thread(
                self._handle_text_message_sync,
                session_id,
                text,
                restaurant_code,
                branch_code,
                idempotency_key,
            )

    def _handle_text_message_sync(
        self,
        session_id: str,
        text: str,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        state = self._store_get(session_id, restaurant_code, branch_code)
        orchestrator = self.orchestrator_factory(restaurant_code, branch_code) if self.orchestrator_factory else self.orchestrator
        result = orchestrator.handle_user_message(text, state)
        persistence_result = None
        if result["trace"].get("selectedHandler") == "submit_order" and self.order_persistence_service:
            persistence_result = self.order_persistence_service.confirm_order(
                session_key=session_id,
                state=result["raw_state"],
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                idempotency_key=idempotency_key,
            )
            result["response"] = (
                f"订单已确认并保存到模拟系统，模拟订单号 {persistence_result.public_id}；"
                "尚未发送给真实餐厅。"
            )
            result["trace"].update(
                {
                    "lifecycleStatus": persistence_result.lifecycle_status,
                    "merchantStatus": persistence_result.merchant_status,
                    "idempotentReplay": persistence_result.idempotent_replay,
                    "subtotalMinor": persistence_result.subtotal_minor,
                    "deliveryFeeMinor": persistence_result.delivery_fee_minor,
                    "totalMinor": persistence_result.total_minor,
                    "currency": persistence_result.currency,
                }
            )
            result["state"] = result["raw_state"].serializable()
        else:
            self._store_set(session_id, result["raw_state"], restaurant_code, branch_code)
        return {
            "session_id": session_id,
            "response": result["response"],
            "state": result["state"],
            "trace": result["trace"],
            "raw_state": result["raw_state"],
            "lifecycle_status": result["raw_state"].lifecycle_status,
            "merchant_status": result["raw_state"].merchant_status,
            "submitted_deprecated": result["raw_state"].submitted,
        }

    def _store_get(self, session_id: str, restaurant_code: str | None, branch_code: str | None):
        if restaurant_code is None and branch_code is None:
            return self.store.get(session_id)
        return self.store.get(session_id, restaurant_code, branch_code)

    def _store_set(self, session_id: str, state, restaurant_code: str | None, branch_code: str | None) -> None:
        if restaurant_code is None and branch_code is None:
            self.store.set(session_id, state)
            return
        self.store.set(session_id, state, restaurant_code, branch_code)
