from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from app.agents.orchestrator import OrchestratorAgent
from app.services.order_persistence_service import OrderPersistenceService
from app.domain.enums import DecisionClass, HandoffStatus
from app.domain.safety import ConfidenceMetadata, SafetyEvaluationContext
from app.services.safety_audit_service import SafetyAuditService
from app.services.handoff_service import HandoffService
from app.services.safety_signal_detector import SafetySignalDetector
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
        safety_audit_service: SafetyAuditService | None = None,
        handoff_service: HandoffService | None = None,
        safety_signal_detector: SafetySignalDetector | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.lock_manager = lock_manager or SessionLockManager()
        self.orchestrator_factory = orchestrator_factory
        self.order_persistence_service = order_persistence_service
        self.safety_audit_service = safety_audit_service
        self.handoff_service = handoff_service
        self.safety_signal_detector = safety_signal_detector or SafetySignalDetector()

    async def handle_text_message(
        self,
        session_id: str,
        text: str,
        *,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
        confidence_metadata: dict[str, Any] | None = None,
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
                confidence_metadata,
            )

    def _handle_text_message_sync(
        self,
        session_id: str,
        text: str,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
        confidence_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self._store_get(session_id, restaurant_code, branch_code)
        if self.safety_audit_service and self.handoff_service:
            guarded = self._handle_safety_preflight(
                session_id=session_id,
                text=text,
                state=state,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                confidence_metadata=confidence_metadata,
            )
            if guarded is not None:
                return guarded
        orchestrator = self.orchestrator_factory(restaurant_code, branch_code) if self.orchestrator_factory else self.orchestrator
        result = orchestrator.handle_user_message(text, state)
        safety_record = None
        if self.safety_audit_service:
            post_signals = self._postflight_signals(result)
            trace_confidence = result.get("trace", {}).get("interpretation", {}).get("confidence")
            confidence = ConfidenceMetadata.from_mapping(
                confidence_metadata
                or ({"overall_confidence": trace_confidence} if trace_confidence is not None else None)
            )
            safety_record = self.safety_audit_service.evaluate_and_record(
                session_key=session_id,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                context=SafetyEvaluationContext(
                    signals=frozenset(post_signals),
                    requested_action=result["trace"].get("selectedHandler") or "READ_ONLY",
                    confidence=confidence,
                    deterministic_input=True,
                ),
            )
            self._apply_safety_state(result["raw_state"], safety_record)
            result["trace"]["safety"] = self._safety_trace(safety_record)
            if safety_record.decision.classification == DecisionClass.HANDOFF and self.handoff_service:
                handoff = self.handoff_service.request_handoff(
                    session_key=session_id,
                    state=state,
                    decision=safety_record.decision,
                    trace_id=safety_record.trace_id,
                    restaurant_code=restaurant_code,
                    branch_code=branch_code,
                )
                self._apply_handoff_state(result["raw_state"], handoff)
                self._store_set(session_id, result["raw_state"], restaurant_code, branch_code)
                return self._guarded_result(
                    session_id,
                    result["raw_state"],
                    "已进入模拟人工接管流程（不是真实人工）；当前订单不会自动提交。",
                    result["trace"],
                )
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

    def _handle_safety_preflight(
        self,
        *,
        session_id: str,
        text: str,
        state,
        restaurant_code: str | None,
        branch_code: str | None,
        confidence_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        normalized = text.casefold()
        if state.handoff_public_id:
            latest_handoff = self.handoff_service.get(
                state.handoff_public_id,
                restaurant_code,
                branch_code,
            )
            state.handoff_status = latest_handoff["status"]
        if state.handoff_public_id and (
            "取消人工接管" in normalized or "取消转人工" in normalized or "cancel handoff" in normalized
        ):
            handoff = self.handoff_service.cancel(
                state.handoff_public_id,
                restaurant_code,
                branch_code,
            )
            state.handoff_status = handoff["status"]
            self._store_set(session_id, state, restaurant_code, branch_code)
            return self._guarded_result(
                session_id,
                state,
                "模拟人工接管已取消；订单草稿仍保留，未提交也未取消。",
                {"safety": {"classification": state.safety_classification, "handoff": handoff}},
            )

        signals = set(self.safety_signal_detector.detect(text))
        blocking_statuses = {
            HandoffStatus.REQUESTED.value,
            HandoffStatus.PENDING.value,
            HandoffStatus.SIMULATED_AGENT_ASSIGNED.value,
            HandoffStatus.SIMULATED_AGENT_CONNECTED.value,
            HandoffStatus.FAILED.value,
        }
        mandatory_cancelled = (
            state.handoff_status == HandoffStatus.CANCELLED.value
            and state.safety_reason_code not in {None, "EXPLICIT_HUMAN_REQUEST"}
        )
        if state.safety_reason_code and (state.handoff_status in blocking_statuses or mandatory_cancelled):
            signals.add(state.safety_reason_code)
        if not signals and confidence_metadata is None:
            return None

        record = self.safety_audit_service.evaluate_and_record(
            session_key=session_id,
            restaurant_code=restaurant_code,
            branch_code=branch_code,
            context=SafetyEvaluationContext(
                signals=frozenset(signals),
                requested_action="USER_MESSAGE",
                confidence=ConfidenceMetadata.from_mapping(confidence_metadata),
                deterministic_input=bool(signals),
            ),
        )
        self._apply_safety_state(state, record)
        trace = {"safety": self._safety_trace(record)}
        if record.decision.classification == DecisionClass.REFUSE:
            return self._guarded_result(
                session_id,
                state,
                "此操作无法执行。你仍可继续处理自己的模拟订单。",
                trace,
            )
        if record.decision.classification == DecisionClass.HANDOFF:
            self._invalidate_confirmation_for_handoff(state)
            handoff = self.handoff_service.request_handoff(
                session_key=session_id,
                state=state,
                decision=record.decision,
                trace_id=record.trace_id,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
            )
            self._apply_handoff_state(state, handoff)
            self._store_set(session_id, state, restaurant_code, branch_code)
            trace["safety"]["handoff"] = handoff
            return self._guarded_result(
                session_id,
                state,
                "已请求模拟人工接管（不是真实人工）；当前订单已冻结且不会自动提交。",
                trace,
            )
        if record.decision.classification == DecisionClass.CONFIRM:
            return self._guarded_result(
                session_id,
                state,
                "我还不能安全确认你的意思，请明确确认或重新说明关键信息。",
                trace,
            )
        return None

    @staticmethod
    def _postflight_signals(result: dict[str, Any]) -> set[str]:
        trace = result.get("trace", {})
        selected = trace.get("selectedHandler")
        final_intent = trace.get("finalIntent")
        signals: set[str] = set()
        if selected == "submit_order":
            signals.add("FINAL_ORDER")
            signals.add("CONFIRMATION_SUCCEEDED")
        if final_intent in {"unknown", "clarify"} or selected in {"fallback", "context_repair"}:
            signals.add("MISUNDERSTANDING")
        else:
            signals.add("UNDERSTOOD")
        raw_state = result.get("raw_state")
        if raw_state and raw_state.pending_delivery_address_candidate:
            signals.add("ADDRESS")
        return signals

    @staticmethod
    def _apply_safety_state(state, record) -> None:
        decision = record.decision
        state.safety_classification = decision.classification.value
        state.safety_reason_code = decision.reason_code
        state.safety_decision_id = record.public_id
        state.safety_blocked_actions = list(decision.blocked_actions)
        state.unconfirmed_fields = list(decision.required_confirmations)

    @staticmethod
    def _apply_handoff_state(state, handoff: dict[str, Any]) -> None:
        state.handoff_public_id = handoff["handoffId"]
        state.handoff_status = handoff["status"]
        summary = handoff.get("summary") or {}
        state.confirmed_fields = list(summary.get("confirmedFields") or [])
        state.unconfirmed_fields = list(summary.get("unconfirmedFields") or [])

    @staticmethod
    def _invalidate_confirmation_for_handoff(state) -> None:
        if state.confirmation_valid or state.submitted:
            state.draft_version += 1
        state.confirmation_valid = False
        state.submitted = False
        state.submitted_order_id = None
        state.lifecycle_status = "DRAFT"

    @staticmethod
    def _safety_trace(record) -> dict[str, Any]:
        return {
            "decisionId": record.public_id,
            "traceId": record.trace_id,
            **record.decision.serializable(),
            "counters": {
                "consecutiveLowConfidence": record.counters.consecutive_low_confidence,
                "consecutiveMisunderstandings": record.counters.consecutive_misunderstandings,
                "consecutiveCorrections": record.counters.consecutive_corrections,
                "confirmationFailures": record.counters.confirmation_failures,
            },
        }

    @staticmethod
    def _guarded_result(session_id: str, state, response: str, trace: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "response": response,
            "state": state.serializable(),
            "trace": trace,
            "raw_state": state,
            "lifecycle_status": state.lifecycle_status,
            "merchant_status": state.merchant_status,
            "submitted_deprecated": state.submitted,
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
