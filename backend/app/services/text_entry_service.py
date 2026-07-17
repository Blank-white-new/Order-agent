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
from app.domain.errors import invalid_locale, invalid_text_input
from app.i18n.text_normalizer import TextInputError


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
        multilingual_text_service=None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.lock_manager = lock_manager or SessionLockManager()
        self.orchestrator_factory = orchestrator_factory
        self.order_persistence_service = order_persistence_service
        self.safety_audit_service = safety_audit_service
        self.handoff_service = handoff_service
        self.safety_signal_detector = safety_signal_detector or SafetySignalDetector()
        self.multilingual_text_service = multilingual_text_service

    async def handle_text_message(
        self,
        session_id: str,
        text: str,
        *,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
        confidence_metadata: dict[str, Any] | None = None,
        locale: str | None = None,
        locale_hint: str | None = None,
        locale_locked: bool | None = None,
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
                locale,
                locale_hint,
                locale_locked,
            )

    def _handle_text_message_sync(
        self,
        session_id: str,
        text: str,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
        confidence_metadata: dict[str, Any] | None = None,
        locale: str | None = None,
        locale_hint: str | None = None,
        locale_locked: bool | None = None,
    ) -> dict[str, Any]:
        state = self._store_get(session_id, restaurant_code, branch_code)
        analysis = None
        if self.multilingual_text_service:
            try:
                analysis = self.multilingual_text_service.analyze(
                    text,
                    state,
                    restaurant_code=restaurant_code,
                    branch_code=branch_code,
                    locale=locale,
                    locale_hint=locale_hint,
                    locale_locked=locale_locked,
                )
            except TextInputError as exc:
                raise invalid_text_input(exc.code) from exc
            except ValueError as exc:
                if "locale" in str(exc).casefold():
                    raise invalid_locale() from exc
                raise
            self.multilingual_text_service.apply_locale_state(state, analysis)
            # A language command may share an utterance with a safety signal.  The
            # switch is immediate only when there is no new risk to classify;
            # otherwise the unchanged Phase 3 safety preflight remains authoritative.
            if analysis.explicit_switch and not analysis.safety_signals:
                self._store_set(session_id, state, restaurant_code, branch_code)
                return self._switch_language_result(session_id, state, analysis)
            repeated_clarification = self._is_repeated_canonical_clarification(
                state,
                analysis,
            )
            self._apply_canonical_clarification_state(state, analysis)
            if repeated_clarification:
                self._store_set(session_id, state, restaurant_code, branch_code)
                repeated = self._guarded_result(
                    session_id,
                    state,
                    self.multilingual_text_service.response_renderer.render_item_candidates(
                        analysis.parsed,
                        analysis.menu_entries,
                    ),
                    {
                        "selectedAgent": "OrchestratorAgent",
                        "selectedHandler": "multilingual_clarification_replay",
                        "finalIntent": "clarify",
                        "fallbackUsed": False,
                        "stateMutationAllowed": False,
                        "stateMutationRejectedReason": "same_clarification_pending",
                        "safety": {
                            "classification": DecisionClass.CONFIRM.value,
                            "reason_code": None,
                        },
                    },
                )
                return self._decorate_multilingual_result(
                    repeated,
                    analysis,
                    guarded=True,
                )
        if self.safety_audit_service and self.handoff_service:
            guarded = self._handle_safety_preflight(
                session_id=session_id,
                text=text,
                state=state,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                confidence_metadata=confidence_metadata,
                extra_signals=analysis.safety_signals if analysis else (),
                required_confirmations=(analysis.parsed.required_confirmations if analysis else ()),
                parsed_confidence=(analysis.parsed.confidence.summary() if analysis else None),
            )
            if guarded is not None:
                if analysis:
                    if guarded["trace"].get("safety", {}).get("classification") != DecisionClass.HANDOFF.value:
                        self._store_set(session_id, state, restaurant_code, branch_code)
                    return self._decorate_multilingual_result(guarded, analysis, guarded=True)
                return guarded
        if analysis and not analysis.parsed.canonical_text:
            self._store_set(session_id, state, restaurant_code, branch_code)
            unknown = self._guarded_result(
                session_id,
                state,
                "我还不能安全确认你的意思，请重新说明要查看或修改的内容。",
                {
                    "selectedAgent": "OrchestratorAgent",
                    "selectedHandler": "multilingual_unknown",
                    "finalIntent": "unknown",
                    "fallbackUsed": False,
                    "stateMutationAllowed": False,
                    "stateMutationRejectedReason": "multilingual_canonical_text_unavailable",
                    "lifecycleStatus": state.lifecycle_status,
                    "merchantStatus": state.merchant_status,
                },
            )
            return self._decorate_multilingual_result(unknown, analysis, guarded=True)
        orchestrator = self.orchestrator_factory(restaurant_code, branch_code) if self.orchestrator_factory else self.orchestrator
        operation_text = analysis.parsed.canonical_text if analysis else text
        result = orchestrator.handle_user_message(operation_text, state)
        if analysis:
            result.setdefault("trace", {})["executionPath"] = "CANONICAL_MULTILINGUAL"
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
                guarded_result = self._guarded_result(
                    session_id,
                    result["raw_state"],
                    "已进入模拟人工接管流程（不是真实人工）；当前订单不会自动提交。",
                    result["trace"],
                )
                return self._decorate_multilingual_result(guarded_result, analysis, guarded=True) if analysis else guarded_result
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
        final_result = {
            "session_id": session_id,
            "response": result["response"],
            "state": result["state"],
            "trace": result["trace"],
            "raw_state": result["raw_state"],
            "lifecycle_status": result["raw_state"].lifecycle_status,
            "merchant_status": result["raw_state"].merchant_status,
            "submitted_deprecated": result["raw_state"].submitted,
        }
        return self._decorate_multilingual_result(final_result, analysis, guarded=False) if analysis else final_result

    def _handle_safety_preflight(
        self,
        *,
        session_id: str,
        text: str,
        state,
        restaurant_code: str | None,
        branch_code: str | None,
        confidence_metadata: dict[str, Any] | None,
        extra_signals: tuple[str, ...] = (),
        required_confirmations: tuple[str, ...] = (),
        parsed_confidence: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        normalized = text.casefold()
        if state.handoff_public_id:
            latest_handoff = self.handoff_service.get(
                state.handoff_public_id,
                restaurant_code,
                branch_code,
                session_id,
            )
            state.handoff_status = latest_handoff["status"]
        if state.handoff_public_id and (
            "取消人工接管" in normalized or "取消转人工" in normalized or "cancel handoff" in normalized
        ):
            handoff = self.handoff_service.cancel(
                state.handoff_public_id,
                restaurant_code,
                branch_code,
                session_id,
            )
            self._apply_cancellation_state(state, handoff)
            if handoff["idempotentReplay"] and not handoff["requiresNewConfirmation"]:
                response = "模拟接管此前已取消；当前订单状态未被更改。"
            elif handoff["mayContinueDraft"]:
                response = "模拟人工接管已取消。订单草稿仍保留。需要重新确认后才能继续。"
            else:
                response = "模拟接管已取消，但安全限制仍然有效。订单不会自动提交。"
            return self._guarded_result(
                session_id,
                state,
                response,
                {"safety": {"classification": state.safety_classification, "handoff": handoff}},
            )

        signals = set(self.safety_signal_detector.detect(text))
        signals.update(extra_signals)
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
        if not signals and confidence_metadata is None and not required_confirmations:
            return None

        record = self.safety_audit_service.evaluate_and_record(
            session_key=session_id,
            restaurant_code=restaurant_code,
            branch_code=branch_code,
            context=SafetyEvaluationContext(
                signals=frozenset(signals),
                requested_action="USER_MESSAGE",
                required_confirmations=required_confirmations,
                confidence=ConfidenceMetadata.from_mapping(confidence_metadata or parsed_confidence),
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
    def _apply_cancellation_state(state, handoff: dict[str, Any]) -> None:
        if handoff["idempotentReplay"] and not handoff["requiresNewConfirmation"]:
            return
        state.handoff_status = handoff["status"]
        state.confirmation_valid = False
        state.submitted = False
        state.submitted_order_id = None
        state.lifecycle_status = handoff["lifecycleStatus"]
        state.stage = "ordering"
        state.draft_version = handoff["draftVersion"]
        state.persistence_version = handoff["persistenceVersion"]
        state.confirmed_fields = []
        if "final_order" not in state.unconfirmed_fields:
            state.unconfirmed_fields.append("final_order")
        if handoff["mayContinueDraft"]:
            state.safety_blocked_actions = []

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

    @staticmethod
    def _apply_canonical_clarification_state(state, analysis) -> None:
        if "AMBIGUOUS_ITEM" not in analysis.parsed.ambiguities:
            return
        candidate_codes = set(analysis.parsed.entities.get("item_candidates", []))
        candidates = [
            {"name": entry.internal_name}
            for entry in analysis.menu_entries
            if entry.code in candidate_codes
        ]
        if candidates:
            state.pending_action = {
                "type": "select_ambiguous_dish_candidate",
                "candidates": candidates,
                "source_text": "[canonical multilingual clarification]",
            }
            state.stage = "ordering"

    @staticmethod
    def _is_repeated_canonical_clarification(state, analysis) -> bool:
        if (
            "AMBIGUOUS_ITEM" not in analysis.parsed.ambiguities
            or analysis.parsed.safety_signals
            or analysis.unsupported_language
            or state.safety_classification != DecisionClass.CONFIRM.value
            or not state.pending_action
            or state.pending_action.get("type") != "select_ambiguous_dish_candidate"
        ):
            return False
        candidate_codes = set(analysis.parsed.entities.get("item_candidates", []))
        expected_names = {
            entry.internal_name
            for entry in analysis.menu_entries
            if entry.code in candidate_codes
        }
        pending_names = {
            candidate.get("name")
            for candidate in state.pending_action.get("candidates", [])
        }
        return bool(expected_names) and pending_names == expected_names

    def _store_get(self, session_id: str, restaurant_code: str | None, branch_code: str | None):
        if restaurant_code is None and branch_code is None:
            return self.store.get(session_id)
        return self.store.get(session_id, restaurant_code, branch_code)

    def _store_set(self, session_id: str, state, restaurant_code: str | None, branch_code: str | None) -> None:
        if restaurant_code is None and branch_code is None:
            self.store.set(session_id, state)
            return
        self.store.set(session_id, state, restaurant_code, branch_code)

    def _switch_language_result(self, session_id: str, state, analysis) -> dict[str, Any]:
        response = self.multilingual_text_service.response_renderer.render_switch(state.response_locale)
        result = self._guarded_result(
            session_id,
            state,
            response,
            {
                "selectedAgent": "OrchestratorAgent",
                "selectedHandler": "switch_language",
                "finalIntent": "switch_language",
                "stateMutationAllowed": False,
                "lifecycleStatus": state.lifecycle_status,
                "merchantStatus": state.merchant_status,
            },
        )
        return self._decorate_multilingual_result(result, analysis, guarded=False)

    def _decorate_multilingual_result(self, result: dict[str, Any], analysis, *, guarded: bool) -> dict[str, Any]:
        context = analysis.parsed.locale_context
        trace = result.setdefault("trace", {})
        trace.setdefault(
            "executionPath",
            "CANONICAL_MULTILINGUAL_GUARDED"
            if guarded
            else "CANONICAL_MULTILINGUAL_CONTROL",
        )
        trace["multilingual"] = analysis.parsed.serializable()
        if analysis.parsed.canonical_intent in {"SET_ADDRESS", "SET_PHONE", "ADD_NOTE"}:
            trace.pop("userMessage", None)
            trace.pop("normalizedMessage", None)
        safety = trace.get("safety", {})
        if guarded and "AMBIGUOUS_ITEM" in analysis.parsed.ambiguities:
            result["response"] = self.multilingual_text_service.response_renderer.render_item_candidates(
                analysis.parsed,
                analysis.menu_entries,
            )
        elif analysis.parsed.canonical_intent == "SWITCH_LANGUAGE":
            result["response"] = self.multilingual_text_service.response_renderer.render_switch(
                context.response_locale
            )
        elif (
            guarded
            and safety.get("classification") in {"REFUSE", "HANDOFF", "CONFIRM"}
            and (
                context.response_locale != "zh-CN"
                or context.requested_locale is not None
                or context.detected_locale == "mixed"
                or context.locale_locked
            )
        ):
            result["response"] = self.multilingual_text_service.response_renderer.render_safety(
                context.response_locale,
                safety.get("classification"),
                safety.get("reason_code"),
            )
        elif (
            context.response_locale != "zh-CN"
            or context.requested_locale is not None
            or context.detected_locale == "mixed"
        ):
            result["response"] = self.multilingual_text_service.response_renderer.render_result(
                analysis.parsed,
                result,
            )
        result.update(
            {
                "detected_locale": context.detected_locale,
                "dominant_locale": context.dominant_locale,
                "response_locale": context.response_locale,
                "locale_confidence": context.confidence,
                "mixed_language": context.mixed_language,
                "required_confirmations": list(
                    dict.fromkeys(
                        [
                            *analysis.parsed.required_confirmations,
                            *result["raw_state"].unconfirmed_fields,
                        ]
                    )
                ),
            }
        )
        # Safety and locale processing may update the authoritative state after
        # the orchestrator built its snapshot. Never return that stale snapshot.
        result["state"] = result["raw_state"].serializable()
        return result
