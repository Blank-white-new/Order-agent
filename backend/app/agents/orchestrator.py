from __future__ import annotations

import re
from typing import Any

from app.agents.confirmation_agent import ConfirmationAgent
from app.agents.context_repair_agent import ContextRepairAgent
from app.agents.delivery_agent import DeliveryAgent
from app.agents.menu_agent import MenuAgent
from app.agents.order_agent import OrderAgent
from app.agents.recommendation_agent import RecommendationAgent
from app.agents.response_agent import ResponseAgent
from app.agents.semantic_evidence import (
    detect_reference_domain,
    has_option_change_evidence,
    has_quantity_update_evidence,
    has_remove_action_evidence,
    has_replace_action_evidence,
)
from app.agents.semantic_router import SemanticRouterAgent
from app.models.schemas import Interpretation, dump_model
from app.services.delivery_service import DeliveryService
from app.services.llm_client import LLMClientResult, create_llm_fallback_client
from app.services.llm_fallback_prompt import SYSTEM_PROMPT, build_llm_fallback_prompt, sanitize_user_text
from app.services.llm_fallback_validation import (
    build_directed_clarification,
    convert_llm_to_interpretation,
    has_explicit_order_action,
    parse_llm_fallback_payload,
)
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.services.reference_normalizer import normalize_recommendation_ordinal_reference
from app.state.session_state import DeliveryAddressCandidate, OrderItem, SessionState, order_to_dicts


INTENT_HANDLER_MAP: dict[str, dict[str, str]] = {
    "ask_menu": {"agent": "MenuAgent", "handler": "ask_menu"},
    "ask_category": {"agent": "MenuAgent", "handler": "ask_category"},
    "ask_category_group": {"agent": "MenuAgent", "handler": "ask_category_group"},
    "ask_availability": {"agent": "MenuAgent", "handler": "ask_availability"},
    "ask_price": {"agent": "MenuAgent", "handler": "ask_price"},
    "ask_option": {"agent": "MenuAgent", "handler": "ask_option"},
    "ask_ingredient": {"agent": "MenuAgent", "handler": "ask_ingredient"},
    "ask_allergen": {"agent": "MenuAgent", "handler": "ask_allergen"},
    "ask_order_summary": {"agent": "MenuAgent", "handler": "ask_order_summary"},
    "ask_recommendation": {"agent": "RecommendationAgent", "handler": "ask_recommendation"},
    "ask_recommendation_by_category": {"agent": "RecommendationAgent", "handler": "ask_recommendation_by_category"},
    "ask_recommendation_by_category_ranked": {"agent": "RecommendationAgent", "handler": "ask_recommendation_by_category_ranked"},
    "ask_recommendation_by_preference": {"agent": "RecommendationAgent", "handler": "ask_recommendation_by_preference"},
    "ask_recommendation_by_budget": {"agent": "RecommendationAgent", "handler": "ask_recommendation_by_budget"},
    "ask_recommendation_by_speed": {"agent": "RecommendationAgent", "handler": "ask_recommendation_by_speed"},
    "order_food": {"agent": "OrderAgent", "handler": "order_food"},
    "order_multiple_items": {"agent": "OrderAgent", "handler": "order_multiple_items"},
    "order_category_items": {"agent": "OrderAgent", "handler": "order_category_items"},
    "order_category_group_items": {"agent": "OrderAgent", "handler": "order_category_group_items"},
    "repeat_last_item": {"agent": "OrderAgent", "handler": "repeat_last_item"},
    "composite_intent": {"agent": "OrchestratorAgent", "handler": "composite_intent"},
    "conditional_order": {"agent": "OrchestratorAgent", "handler": "conditional_order"},
    "select_recommendation": {"agent": "OrderAgent", "handler": "select_recommendation"},
    "order_by_preference": {"agent": "OrderAgent", "handler": "order_by_preference"},
    "update_item_option": {"agent": "OrderAgent", "handler": "update_item_option"},
    "update_item_quantity": {"agent": "OrderAgent", "handler": "update_item_quantity"},
    "remove_item": {"agent": "OrderAgent", "handler": "remove_item"},
    "remove_category_items": {"agent": "OrderAgent", "handler": "remove_category_items"},
    "replace_item": {"agent": "OrderAgent", "handler": "replace_item"},
    "clear_order": {"agent": "OrderAgent", "handler": "clear_order"},
    "provide_fulfillment_slot": {"agent": "DeliveryAgent", "handler": "provide_fulfillment_slot"},
    "provide_delivery_address": {"agent": "DeliveryAgent", "handler": "provide_delivery_address"},
    "provide_phone": {"agent": "DeliveryAgent", "handler": "provide_phone"},
    "ask_delivery_eta": {"agent": "DeliveryAgent", "handler": "ask_delivery_eta"},
    "ask_delivery_fee": {"agent": "DeliveryAgent", "handler": "ask_delivery_fee"},
    "ask_deliverability": {"agent": "DeliveryAgent", "handler": "ask_deliverability"},
    "confirm_delivery_candidate": {"agent": "DeliveryAgent", "handler": "confirm_pending_address"},
    "reject_delivery_candidate": {"agent": "DeliveryAgent", "handler": "reject_pending_address"},
    "replace_delivery_candidate": {"agent": "DeliveryAgent", "handler": "address_candidate"},
    "conditional_fulfillment": {"agent": "DeliveryAgent", "handler": "conditional_fulfillment"},
    "context_correction": {"agent": "ContextRepairAgent", "handler": "context_correction"},
    "context_reference_resolution": {"agent": "ContextRepairAgent", "handler": "context_reference_resolution"},
    "confirm": {"agent": "ConfirmationAgent", "handler": "confirm"},
    "cancel": {"agent": "ResponseAgent", "handler": "cancel"},
    "smalltalk": {"agent": "ResponseAgent", "handler": "smalltalk"},
    "reject_request": {"agent": "ResponseAgent", "handler": "reject_request"},
    "hold_order": {"agent": "ResponseAgent", "handler": "hold_order"},
    "fallback": {"agent": "FallbackAgent", "handler": "fallback"},
}


NO_MUTATION_INTENTS = {
    "ask_menu",
    "ask_category",
    "ask_category_group",
    "ask_availability",
    "ask_price",
    "ask_option",
    "ask_ingredient",
    "ask_allergen",
    "ask_order_summary",
    "ask_delivery_eta",
    "ask_delivery_fee",
    "ask_deliverability",
    "smalltalk",
    "reject_request",
    "hold_order",
}

PENDING_ACTION_CANCEL_INTENTS = {"cancel", "cancel_ambiguous_selection"}
PENDING_ACTION_CONFIRM_INTENTS = {"confirm"}
ADDRESS_CANDIDATE_LIVE_INTENTS = {
    "confirm_delivery_candidate",
    "reject_delivery_candidate",
    "replace_delivery_candidate",
    "smalltalk",
    "fallback",
}

NEW_ORDER_COMMANDS = {
    "重新下单",
    "再来一单",
    "开始新订单",
    "新订单",
    "重新点一份",
}
SUBMITTED_CONFIRMATION_COMMANDS = {
    "确认",
    "确认订单",
    "确认下单",
    "确认提交",
    "就这些",
    "就这些可以下单了",
    "可以下单了",
    "下单",
    "提交订单",
}


class OrchestratorAgent:
    def __init__(self) -> None:
        self.menu_service = MenuService()
        self.delivery_service = DeliveryService()
        self.order_service = OrderService()
        self.semantic_router = SemanticRouterAgent(self.menu_service)
        self.llm_client = create_llm_fallback_client()
        self.menu_agent = MenuAgent(self.menu_service, self.order_service)
        self.recommendation_agent = RecommendationAgent(self.menu_service)
        self.order_agent = OrderAgent(self.menu_service, self.order_service)
        self.delivery_agent = DeliveryAgent(self.delivery_service)
        self.context_repair_agent = ContextRepairAgent()
        self.confirmation_agent = ConfirmationAgent(self.order_service, self.menu_service)
        self.response_agent = ResponseAgent()

    def handle_user_message(self, user_message: str, session_state: SessionState | None = None) -> dict[str, Any]:
        state = session_state or SessionState()
        before = state.clone()
        normalized = self.semantic_router.normalize(user_message)
        if state.submitted or state.submitted_order_id:
            return self._handle_submitted_lifecycle(user_message, normalized, state, before)
        interpretation = self.semantic_router.interpret(user_message)
        interpretation, llm_fallback_trace = self._merge_llm_interpretation(user_message, interpretation, state)
        interpretation = self._apply_contextual_intent(interpretation, normalized, state)
        interpretation = self._resolve_context_reference(interpretation, state)
        self._expire_stale_pending_state(interpretation, state)

        rollback_applied = False
        rollback_reason = None
        rolled_back_fields: list[str] = []
        composite_children = None
        conditional_decision = interpretation.entities.get("conditionalDecision")

        if interpretation.intent == "composite_intent":
            action_result = self._handle_composite(interpretation, state)
            rejected_reason = None
            mutation_allowed = True
            composite_children = action_result.get("compositeChildren", [])
            self._record_mutation_snapshot(state, before, state.clone(), user_message, "composite_intent", confirmed=False)
        elif interpretation.intent == "conditional_order":
            action_result = self._handle_conditional_order(interpretation)
            rejected_reason = self._validate_state_patch(interpretation.intent, action_result.get("patch", {}), state)
            mutation_allowed = rejected_reason is None
            if mutation_allowed:
                self._apply_patch(state, action_result.get("patch", {}))
        else:
            action_result = self._dispatch(interpretation, state)
            rejected_reason = self._validate_state_patch(interpretation.intent, action_result.get("patch", {}), state)
            mutation_allowed = rejected_reason is None
            if mutation_allowed:
                patch = action_result.get("patch", {})
                self._apply_patch(state, patch)
                if interpretation.intent == "context_correction":
                    rollback_applied, rollback_reason, rolled_back_fields = self._maybe_apply_rollback(normalized, state)
                    if rollback_applied:
                        action_result["message"] = "好的，已撤回刚才加入的内容。你可以继续看菜单或重新点。"
                skip_snapshot = (
                    (interpretation.intent == "context_correction" and rollback_applied)
                    or action_result.get("handler") == "clear_order"
                )
                if not skip_snapshot:
                    self._record_mutation_snapshot(
                        state,
                        before,
                        state.clone(),
                        user_message,
                        action_result.get("handler", interpretation.intent),
                        confirmed=action_result.get("handler") in ("submit_order", "clear_order"),
                    )

        response = self.response_agent.generate(action_result, state)
        trace = {
            "userMessage": user_message,
            "normalizedMessage": normalized,
            "finalIntent": interpretation.intent,
            "selectedAgent": action_result.get("agent"),
            "selectedHandler": action_result.get("handler"),
            "interpretationSource": interpretation.source,
            "fallbackUsed": interpretation.intent == "fallback",
            "stateMutationAllowed": mutation_allowed,
            "stateMutationRejectedReason": rejected_reason,
            "rollbackApplied": rollback_applied,
            "rollbackReason": rollback_reason,
            "rolledBackFields": rolled_back_fields,
            "compositeChildren": composite_children,
            "conditionalDecision": conditional_decision,
            "semanticEvidenceReason": interpretation.entities.get("semantic_evidence_reason")
            or interpretation.entities.get("clarification"),
            "referenceDomain": interpretation.entities.get("reference_domain"),
            "currentStageBefore": before.stage,
            "currentStageAfter": state.stage,
            "orderBefore": order_to_dicts(before.current_order),
            "orderAfter": order_to_dicts(state.current_order),
            "officialAddressBefore": before.official_delivery_address,
            "officialAddressAfter": state.official_delivery_address,
            "pendingCandidateBefore": dump_model(before.pending_delivery_address_candidate),
            "pendingCandidateAfter": dump_model(state.pending_delivery_address_candidate),
            "response": response,
        }
        trace.update(llm_fallback_trace)
        if trace.get("llmFallbackShadow"):
            trace = self._sanitize_shadow_trace(trace)
        return {"response": response, "state": state.serializable(), "trace": trace, "raw_state": state}

    def _handle_submitted_lifecycle(
        self,
        user_message: str,
        normalized: str,
        state: SessionState,
        before: SessionState,
    ) -> dict[str, Any]:
        command = normalized.rstrip("，,。！？!?")
        order_id = state.submitted_order_id or "当前订单"

        if command in NEW_ORDER_COMMANDS:
            self._apply_patch(state, SessionState().serializable())
            final_intent = "start_new_order"
            selected_agent = "OrchestratorAgent"
            selected_handler = "start_new_order"
            response = "已开始新订单，旧订单不会被修改。请告诉我这次想点什么。"
            mutation_allowed = True
            rejected_reason = None
            lifecycle_reason = "new_order_started"
        elif command in SUBMITTED_CONFIRMATION_COMMANDS:
            final_intent = "confirm"
            selected_agent = "ConfirmationAgent"
            selected_handler = "order_already_submitted"
            response = f"订单已提交，订单号 {order_id}。如需重新下单，请说“重新下单”或“再来一单”。"
            mutation_allowed = False
            rejected_reason = "order_already_submitted"
            lifecycle_reason = "order_already_submitted"
        else:
            final_intent = "submitted_order_locked"
            selected_agent = "ResponseAgent"
            selected_handler = "submitted_order_locked"
            response = (
                f"订单已提交，订单号 {order_id}，不能继续修改。"
                "如需重新下单，请说“重新下单”或“再来一单”。"
            )
            mutation_allowed = False
            rejected_reason = "submitted_order_locked"
            lifecycle_reason = "new_order_required"

        trace = {
            "userMessage": user_message,
            "normalizedMessage": normalized,
            "finalIntent": final_intent,
            "selectedAgent": selected_agent,
            "selectedHandler": selected_handler,
            "interpretationSource": "rule",
            "fallbackUsed": False,
            "stateMutationAllowed": mutation_allowed,
            "stateMutationRejectedReason": rejected_reason,
            "lifecycleReason": lifecycle_reason,
            "rollbackApplied": False,
            "rollbackReason": None,
            "rolledBackFields": [],
            "compositeChildren": None,
            "conditionalDecision": None,
            "currentStageBefore": before.stage,
            "currentStageAfter": state.stage,
            "orderBefore": order_to_dicts(before.current_order),
            "orderAfter": order_to_dicts(state.current_order),
            "officialAddressBefore": before.official_delivery_address,
            "officialAddressAfter": state.official_delivery_address,
            "pendingCandidateBefore": dump_model(before.pending_delivery_address_candidate),
            "pendingCandidateAfter": dump_model(state.pending_delivery_address_candidate),
            "response": response,
        }
        trace.update(self._new_llm_fallback_trace())
        return {"response": response, "state": state.serializable(), "trace": trace, "raw_state": state}

    def _merge_llm_interpretation(
        self,
        message: str,
        interpretation: Interpretation,
        state: SessionState,
    ) -> tuple[Interpretation, dict[str, Any]]:
        trace = self._new_llm_fallback_trace()
        shadow = bool(getattr(self.llm_client, "is_shadow", False))
        trace["llmFallbackMode"] = str(getattr(self.llm_client, "runtime_mode", "disabled"))
        trace["llmFallbackShadow"] = shadow
        trace["llmFallbackSandboxSource"] = getattr(self.llm_client, "sandbox_source", None)
        trace["llmFallbackEnabled"] = self._llm_is_enabled()
        trace["llmFallbackConfigured"] = self._llm_is_configured()
        trace["llmFallbackTimeoutSeconds"] = getattr(self.llm_client, "timeout_seconds", None)
        trigger_reason = self._llm_fallback_trigger_reason(message, interpretation, state)
        trace["llmFallbackReason"] = trigger_reason
        if not trigger_reason:
            return interpretation, trace
        if not self._llm_can_call():
            trace["llmFallbackDegraded"] = True
            trace["llmFallbackDegradeReason"] = (
                getattr(self.llm_client, "config_error", None)
                or ("disabled" if not trace["llmFallbackEnabled"] else "missing_config")
            )
            return interpretation, trace

        prompt = build_llm_fallback_prompt(
            message,
            state,
            self.menu_service,
            top_n=getattr(self.llm_client, "top_candidates", 8),
        )
        trace["llmFallbackTriggered"] = True
        raw_result = self._call_llm_client(message, prompt)
        result = self._coerce_llm_result(raw_result)
        trace["llmFallbackLatencyMs"] = result.latency_ms
        trace["llmFallbackTimedOut"] = result.timed_out
        trace["llmFallbackParseOk"] = result.parse_ok
        if not result.ok:
            trace["llmFallbackDegraded"] = True
            trace["llmFallbackDegradeReason"] = result.status
            if shadow:
                trace["llmFallbackValidationRejected"] = True
                trace["llmFallbackValidationRejectReason"] = result.status
                return interpretation, trace
            return self._degraded_llm_interpretation(message, state, result.status), trace

        parsed_result = parse_llm_fallback_payload(result.payload or {})
        if parsed_result.parsed:
            trace["llmFallbackShadowCandidate"] = shadow
            trace["llmFallbackIntent"] = parsed_result.parsed.intent
            trace["llmFallbackConfidence"] = parsed_result.parsed.confidence
            trace["llmFallbackActionCount"] = len(parsed_result.parsed.actions)
            trace["llmFallbackActionTypes"] = [action.type for action in parsed_result.parsed.actions]
        if not parsed_result.ok or parsed_result.parsed is None:
            trace["llmFallbackDegraded"] = True
            trace["llmFallbackDegradeReason"] = parsed_result.reason or "schema_error"
            trace["llmFallbackValidationRejected"] = True
            trace["llmFallbackValidationRejectReason"] = parsed_result.reason or "schema_error"
            if shadow:
                return interpretation, trace
            return self._degraded_llm_interpretation(message, state, parsed_result.reason), trace

        converted = convert_llm_to_interpretation(
            parsed_result.parsed,
            original_message=message,
            menu_service=self.menu_service,
            state=state,
            min_confidence=getattr(self.llm_client, "min_confidence", 0.65),
        )
        trace["llmFallbackValidationOk"] = converted.ok
        trace["llmFallbackValidationAccepted"] = converted.ok
        trace["llmFallbackValidationRejected"] = not converted.ok
        trace["llmFallbackValidationRejectReason"] = None if converted.ok else converted.reason
        if not converted.ok or converted.interpretation is None:
            trace["llmFallbackDegraded"] = True
            trace["llmFallbackDegradeReason"] = converted.reason or "business_validation_failed"
            if shadow:
                return interpretation, trace
            return self._degraded_llm_interpretation(message, state, converted.reason), trace

        trace["llmFallbackWouldMutateOrder"] = bool(converted.interpretation.should_mutate_order)
        if shadow:
            # Shadow observes a validated candidate but deliberately keeps the rules-first interpretation.
            return interpretation, trace

        if converted.interpretation.intent == "fallback":
            directed_message = converted.safe_reply or build_directed_clarification(message, state, converted.reason)
            converted.interpretation = self._copy_interpretation(
                converted.interpretation,
                {"entities": {**converted.interpretation.entities, "directed_message": directed_message}},
            )
        return converted.interpretation, trace

    def _new_llm_fallback_trace(self) -> dict[str, Any]:
        return {
            "llmFallbackEnabled": False,
            "llmFallbackMode": "disabled",
            "llmFallbackShadow": False,
            "llmFallbackSandboxSource": None,
            "llmFallbackShadowCandidate": False,
            "llmFallbackConfigured": False,
            "llmFallbackTriggered": False,
            "llmFallbackReason": None,
            "llmFallbackLatencyMs": None,
            "llmFallbackTimedOut": False,
            "llmFallbackParseOk": False,
            "llmFallbackValidationOk": False,
            "llmFallbackValidationAccepted": False,
            "llmFallbackValidationRejected": False,
            "llmFallbackValidationRejectReason": None,
            "llmFallbackWouldMutateOrder": False,
            "llmFallbackIntent": None,
            "llmFallbackConfidence": None,
            "llmFallbackActionCount": 0,
            "llmFallbackActionTypes": [],
            "llmFallbackDegraded": False,
            "llmFallbackDegradeReason": None,
            "llmFallbackTimeoutSeconds": None,
        }

    def _sanitize_shadow_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        address_keys = {
            "officialAddressBefore",
            "officialAddressAfter",
            "pendingCandidateBefore",
            "pendingCandidateAfter",
        }

        def sanitize(value: Any, key: str | None = None) -> Any:
            if key in address_keys and value:
                return "[address hidden]"
            if isinstance(value, str):
                return sanitize_user_text(value, limit=80)
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, dict):
                return {child_key: sanitize(item, child_key) for child_key, item in value.items()}
            return value

        return sanitize(trace)

    def _llm_is_enabled(self) -> bool:
        checker = getattr(self.llm_client, "is_enabled", None)
        return bool(checker()) if callable(checker) else False

    def _llm_is_configured(self) -> bool:
        checker = getattr(self.llm_client, "is_configured", None)
        return bool(checker()) if callable(checker) else False

    def _llm_can_call(self) -> bool:
        checker = getattr(self.llm_client, "can_call", None)
        if callable(checker):
            return bool(checker())
        return self._llm_is_enabled() and self._llm_is_configured()

    def _llm_fallback_trigger_reason(
        self,
        message: str,
        interpretation: Interpretation,
        state: SessionState,
    ) -> str | None:
        if interpretation.source in {"rule", "deterministic", "merged"} and interpretation.confidence >= 0.85:
            return None
        if state.pending_action and interpretation.intent in PENDING_ACTION_CONFIRM_INTENTS | PENDING_ACTION_CANCEL_INTENTS:
            return None
        if state.pending_delivery_address_candidate and interpretation.intent in ADDRESS_CANDIDATE_LIVE_INTENTS:
            return None
        compact = re.sub(r"[，,。！？!?；;、：:\"'“”‘’（）()【】\[\].…\s-]+", "", message)
        if state.stage in {"collecting_address", "collecting_phone"} and interpretation.intent in {"fallback", "unknown"}:
            return None
        if state.stage == "collecting_address" and self._looks_like_address(compact):
            return None
        if state.pending_delivery_address_candidate and self._looks_like_address(compact):
            return None
        if (
            interpretation.intent in {"fallback", "unknown"}
            and self._looks_like_address(compact)
            and not has_explicit_order_action(message)
        ):
            return None
        min_confidence = getattr(self.llm_client, "min_confidence", 0.65)
        if interpretation.intent in {"fallback", "unknown"}:
            return interpretation.intent
        if interpretation.confidence < min_confidence:
            return "low_confidence"
        return None

    def _call_llm_client(self, message: str, prompt: str) -> Any:
        try:
            return self.llm_client.interpret(message, prompt=prompt, system_prompt=SYSTEM_PROMPT)
        except TypeError:
            return self.llm_client.interpret(message)

    def _coerce_llm_result(self, raw_result: Any) -> LLMClientResult:
        if isinstance(raw_result, LLMClientResult):
            return raw_result
        if isinstance(raw_result, dict):
            return LLMClientResult(status="success", payload=raw_result, parse_ok=True)
        if raw_result is None:
            return LLMClientResult(status="empty_response")
        status = getattr(raw_result, "status", None)
        payload = getattr(raw_result, "payload", None)
        return LLMClientResult(
            status=status or ("success" if payload else "empty_response"),
            payload=payload if isinstance(payload, dict) else None,
            raw_text=getattr(raw_result, "raw_text", None),
            error=getattr(raw_result, "error", None),
            latency_ms=getattr(raw_result, "latency_ms", None),
            timed_out=bool(getattr(raw_result, "timed_out", False)),
            parse_ok=bool(getattr(raw_result, "parse_ok", payload is not None)),
            http_status=getattr(raw_result, "http_status", None),
        )

    def _degraded_llm_interpretation(self, message: str, state: SessionState, reason: str | None) -> Interpretation:
        return Interpretation(
            intent="fallback",
            confidence=0.5,
            source="llm",
            should_mutate_order=False,
            entities={"directed_message": build_directed_clarification(message, state, reason)},
        )

    def _apply_contextual_intent(self, interpretation: Interpretation, normalized: str, state: SessionState) -> Interpretation:
        compact = re.sub(r"[，,。！？!?\s]", "", normalized)

        # --- Ambiguous candidate selection ---
        pending = state.pending_action
        if pending and pending.get("type") == "select_ambiguous_dish_candidate":
            candidates = pending.get("candidates", [])
            # Check for cancel/abort
            if compact in {"算了", "取消", "不要了"}:
                return Interpretation(
                    intent="cancel_ambiguous_selection",
                    confidence=0.98,
                    source="rule",
                    should_mutate_order=False,
                    entities={"clarification": "cancel_ambiguous_selection"},
                )
            # Check for ordinal selection via "第一个"/"第二个"/"第三个"
            ordinal_map = {"第一个": 0, "第二个": 1, "第三个": 2, "1": 0, "2": 1, "3": 2, "一": 0, "二": 1, "三": 2}
            if compact in ordinal_map and len(candidates) > 0:
                idx = min(ordinal_map[compact], len(candidates) - 1)
                return Interpretation(
                    intent="order_food",
                    confidence=0.96,
                    source="rule",
                    should_mutate_order=True,
                    entities={"item_name": candidates[idx]["name"], "quantity": 1},
                    preferences=interpretation.preferences,
                )
            # Check for candidate name match
            for c in candidates:
                if compact == c["name"]:
                    return Interpretation(
                        intent="order_food",
                        confidence=0.96,
                        source="rule",
                        should_mutate_order=True,
                        entities={"item_name": c["name"], "quantity": 1},
                        preferences=interpretation.preferences,
                    )
            # Check for dish fragment match within candidates only
            unique_item = self._resolve_fragment_in_candidates(compact, candidates)
            if unique_item:
                return Interpretation(
                    intent="order_food",
                    confidence=0.94,
                    source="merged",
                    should_mutate_order=True,
                    entities={"item_name": unique_item, "quantity": 1},
                    preferences=interpretation.preferences,
                )

        if compact in {"先别提交我再看看", "先别下单我再看看", "先别提交", "先别下单"}:
            return Interpretation(
                intent="hold_order",
                confidence=0.9,
                source="rule",
                should_mutate_order=False,
                entities={"semantic_evidence_reason": "negative_submission_statement"},
            )

        if interpretation.intent == "ask_recommendation_by_preference" and has_replace_action_evidence(compact):
            return self._context_clarification("missing_replace_target")

        if interpretation.intent == "replace_item":
            return self._resolve_replace_intent(interpretation, compact, state)

        modifier_update = self._contextual_item_modifier_interpretation(interpretation, compact, state)
        if modifier_update:
            return modifier_update

        if interpretation.intent == "order_food" and state.current_order:
            item_name = interpretation.entities.get("item_name")
            relative_quantity = self._relative_quantity_update_interpretation(interpretation, compact, state)
            if relative_quantity:
                return relative_quantity
            if item_name and any(item.name == item_name for item in state.current_order) and self._has_option_change(compact):
                return self._copy_interpretation(
                    interpretation,
                    {"intent": "update_item_option", "confidence": 0.9, "source": "merged", "should_mutate_order": True},
                )
        if interpretation.intent == "confirm" and state.pending_delivery_address_candidate:
            return self._copy_interpretation(interpretation, {"intent": "confirm_delivery_candidate", "confidence": 0.95, "source": "rule"})
        if interpretation.intent == "cancel" and state.pending_delivery_address_candidate:
            return self._copy_interpretation(interpretation, {"intent": "reject_delivery_candidate", "confidence": 0.92, "source": "rule"})
        if interpretation.intent in INTENT_HANDLER_MAP and interpretation.intent not in {"fallback", "cancel"}:
            # If ambiguous candidates are pending and user asks a new question,
            # clear the stale candidate pending
            if pending and pending.get("type") == "select_ambiguous_dish_candidate":
                if interpretation.intent in NO_MUTATION_INTENTS:
                    self._apply_patch(state, {"pending_action": None})
            return interpretation
        if state.stage == "collecting_address" and self._looks_like_address(compact):
            return Interpretation(
                intent="provide_delivery_address",
                confidence=0.88,
                source="deterministic",
                should_mutate_order=True,
                entities={"address": compact},
            )
        if state.stage == "collecting_address" and interpretation.intent in {"fallback", "unknown"}:
            return Interpretation(
                intent="fallback",
                confidence=0.86,
                source="deterministic",
                should_mutate_order=False,
                entities={"directed_message": "请告诉我配送地址。"},
            )
        if state.stage == "collecting_phone" and interpretation.intent in {"fallback", "unknown"}:
            return Interpretation(
                intent="fallback",
                confidence=0.86,
                source="deterministic",
                should_mutate_order=False,
                entities={"directed_message": "请提供联系电话。"},
            )
        if state.pending_delivery_address_candidate and self._looks_like_address(compact):
            return Interpretation(
                intent="replace_delivery_candidate",
                confidence=0.88,
                source="deterministic",
                should_mutate_order=True,
                entities={"address": compact},
            )
        if interpretation.intent == "fallback" and self._looks_like_address(compact):
            return Interpretation(
                intent="replace_delivery_candidate",
                confidence=0.82,
                source="deterministic",
                should_mutate_order=True,
                entities={"address": compact},
            )
        return interpretation

    def _context_clarification(self, reason: str, **entities: Any) -> Interpretation:
        return Interpretation(
            intent="context_correction",
            confidence=0.86,
            source="merged",
            should_mutate_order=False,
            entities={"clarification": reason, "semantic_evidence_reason": reason, **entities},
        )

    def _relative_quantity_update_interpretation(
        self,
        interpretation: Interpretation,
        compact: str,
        state: SessionState,
    ) -> Interpretation | None:
        if "少一" not in compact and "减一" not in compact:
            return None
        item_name = interpretation.entities.get("item_name")
        if not item_name:
            return None
        for item in state.current_order:
            if item.name == item_name:
                new_quantity = max(item.quantity - 1, 0)
                if new_quantity <= 0:
                    return Interpretation(
                        intent="remove_item",
                        confidence=0.9,
                        source="merged",
                        should_mutate_order=True,
                        entities={"item_name": item_name},
                    )
                return Interpretation(
                    intent="update_item_quantity",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"item_name": item_name, "quantity": new_quantity},
                )
        return None

    def _resolve_replace_intent(
        self,
        interpretation: Interpretation,
        compact: str,
        state: SessionState,
    ) -> Interpretation:
        if not state.current_order:
            return self._context_clarification("missing_replace_target")
        if interpretation.entities.get("old_item_name"):
            return interpretation
        new_name = interpretation.entities.get("new_item_name")
        if not new_name:
            return self._context_clarification("missing_replace_target")
        index = self._unique_recent_order_index(state) if any(token in compact for token in ["刚才", "刚加", "这个", "那个", "这份", "那份"]) else None
        if index is None and len(state.current_order) == 1:
            index = 0
        if index is None:
            return self._context_clarification("ambiguous_replace_reference", new_item_name=new_name)
        return self._copy_interpretation(
            interpretation,
            {
                "confidence": 0.92,
                "source": "merged",
                "entities": {**interpretation.entities, "old_item_name": state.current_order[index].name, "index": index},
            },
        )

    def _resolve_context_reference(self, interpretation: Interpretation, state: SessionState) -> Interpretation:
        if interpretation.intent != "context_reference_resolution":
            return interpretation
        raw = interpretation.entities.get("raw", "")
        ref = interpretation.entities.get("reference", "")
        index = self._reference_to_index(ref)
        domain = detect_reference_domain(raw, bool(state.last_recommendations), bool(state.current_order))

        unique_item, all_matches = self._resolve_dish_fragment(raw)
        if unique_item and domain in {"none", "recommendation"}:
            return Interpretation(
                intent="order_food",
                confidence=0.9,
                source="merged",
                should_mutate_order=True,
                entities={"item_name": unique_item.name, "quantity": 1, "reference_domain": domain},
                preferences=interpretation.preferences,
            )
        if all_matches and len(all_matches) > 1:
            names = [item["name"] for item in all_matches]
            return self._context_clarification("ambiguous_dish_fragment", candidates=names, raw=raw, reference_domain=domain)

        if domain == "ambiguous":
            return self._context_clarification("ambiguous_reference_domain", reference_domain=domain)

        if domain == "recommendation":
            if not state.last_recommendations:
                return self._context_clarification("reference_unresolved", reference_domain=domain)
            if index is None:
                if len(state.last_recommendations) == 1 and any(token in raw for token in ["来", "要", "就"]):
                    index = 0
                else:
                    return self._context_clarification(
                        "ambiguous_recommendation_reference",
                        candidates=[rec["name"] for rec in state.last_recommendations[:3]],
                        reference_domain=domain,
                    )
            if index >= len(state.last_recommendations):
                return self._context_clarification("recommendation_index_out_of_range", reference_domain=domain)
            return Interpretation(
                intent="select_recommendation",
                confidence=0.92,
                source="merged",
                should_mutate_order=True,
                entities={"index": index, "reference_domain": domain},
                preferences=interpretation.preferences,
            )

        if domain == "order":
            if not state.current_order:
                return self._context_clarification("reference_unresolved", reference_domain=domain)
            resolved_index = index
            if resolved_index is None and any(token in raw for token in ["刚才", "刚加"]):
                resolved_index = self._unique_recent_order_index(state)
            if resolved_index is None and len(state.current_order) == 1 and any(token in raw for token in ["这个", "那个", "这份", "那份"]):
                resolved_index = 0
            if resolved_index is None or resolved_index >= len(state.current_order):
                return self._context_clarification("ambiguous_order_reference", reference_domain=domain)
            item_name = state.current_order[resolved_index].name
            if has_remove_action_evidence(raw):
                return Interpretation(
                    intent="remove_item",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"index": resolved_index, "item_name": item_name, "reference_domain": domain},
                )
            if has_quantity_update_evidence(raw):
                return Interpretation(
                    intent="update_item_quantity",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={
                        "index": resolved_index,
                        "item_name": item_name,
                        "quantity": self.semantic_router._extract_quantity(raw),
                        "reference_domain": domain,
                    },
                )
            if has_option_change_evidence(raw) or self._has_option_change(raw):
                return Interpretation(
                    intent="update_item_option",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"index": resolved_index, "item_name": item_name, "reference_domain": domain},
                    preferences=interpretation.preferences,
                )
            if has_replace_action_evidence(raw):
                mentioned_items = self.menu_service.find_items_in_text(raw)
                new_item = mentioned_items[-1] if len(mentioned_items) >= 2 else self.menu_service.find_item_by_name(raw)
                if not new_item:
                    return self._context_clarification("missing_replace_target", reference_domain=domain)
                return Interpretation(
                    intent="replace_item",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"old_item_name": item_name, "new_item_name": new_item.name, "reference_domain": domain},
                    preferences=interpretation.preferences,
                )
            return self._context_clarification("reference_unresolved", reference_domain=domain)

        if raw in {"就那个", "要那个", "来那个"}:
            rec_names = None
            if state.last_recommendations:
                rec_names = [rec["name"] for rec in state.last_recommendations[:3]]
            elif state.viewed_category:
                items = self.menu_service.get_available_items_by_category(state.viewed_category)
                rec_names = [item.name for item in items[:4]]
            if rec_names:
                return self._context_clarification("ambiguous_no_dish_fragment", candidates=rec_names)

        if state.current_order and self._has_option_change(raw) and ref in {"这个", "那个", "刚才那个"}:
            if len(state.current_order) > 1 and ref in {"这个", "那个"}:
                return self._context_clarification("ambiguous_order_reference", reference_domain="order")
            resolved_index = self._unique_recent_order_index(state)
            if resolved_index is None:
                return self._context_clarification("ambiguous_order_reference", reference_domain="order")
            return Interpretation(
                intent="update_item_option",
                confidence=0.9,
                source="merged",
                should_mutate_order=True,
                entities={"index": resolved_index, "item_name": state.current_order[resolved_index].name},
                preferences=interpretation.preferences,
            )
        if state.last_recommendations and raw in {"就这个", "要这个", "这些都要"}:
            return Interpretation(
                intent="select_recommendation",
                confidence=0.92,
                source="merged",
                should_mutate_order=True,
                entities={"index": 0},
                preferences=interpretation.preferences,
            )
        return self._context_clarification("reference_unresolved", reference_domain=domain)

    def _dispatch(self, interpretation: Interpretation, state: SessionState) -> dict:
        intent = interpretation.intent
        if intent == "cancel_ambiguous_selection":
            return {
                "agent": "ResponseAgent",
                "handler": "cancel_ambiguous_selection",
                "message": "好的，先不选这个。你可以继续点菜或看菜单。",
                "patch": {"pending_action": None},
            }
        if intent == "fallback":
            return self.response_agent.fallback(interpretation.entities.get("directed_message"))
        if intent not in INTENT_HANDLER_MAP:
            return self.response_agent.fallback()
        mapping = INTENT_HANDLER_MAP[intent]
        agent = mapping["agent"]
        handler = mapping["handler"]
        if agent == "MenuAgent":
            return self.menu_agent.handle(interpretation, state)
        if agent == "RecommendationAgent":
            return self.recommendation_agent.handle(interpretation, state)
        if agent == "OrderAgent":
            return self.order_agent.handle(interpretation, state)
        if agent == "DeliveryAgent":
            return self.delivery_agent.handle(interpretation, state, handler=handler)
        if agent == "ContextRepairAgent":
            return self.context_repair_agent.handle(interpretation, state)
        if agent == "ConfirmationAgent":
            return self.confirmation_agent.handle(interpretation, state)
        if agent == "OrchestratorAgent" and intent == "conditional_order":
            return self._handle_conditional_order(interpretation)
        if agent == "OrchestratorAgent" and intent == "composite_intent":
            return self._handle_composite(interpretation, state)
        if intent == "reject_request":
            return {
                "agent": "ResponseAgent",
                "handler": "reject_request",
                "message": interpretation.entities.get("directed_message", "这个操作不允许。"),
                "patch": {},
            }
        if intent == "hold_order":
            return {
                "agent": "ResponseAgent",
                "handler": "hold_order",
                "message": "好的，先不提交，订单会继续保留。",
                "patch": {},
            }
        if intent == "smalltalk":
            return self.response_agent.smalltalk()
        if intent == "cancel":
            if state.pending_action:
                return {
                    "agent": "ResponseAgent",
                    "handler": "cancel_pending_action",
                    "message": "好的，已取消刚才待确认的操作，订单本身不变。",
                    "patch": {"pending_action": None},
                }
            if state.current_order:
                return {
                    "agent": "ResponseAgent",
                    "handler": "cancel",
                    "message": "你订单里已经有菜了，要清空的话再说“清空订单”。",
                    "patch": {"pending_action": {"type": "confirm_clear_order"}},
                }
            return {
                "agent": "ResponseAgent",
                "handler": "cancel",
                "message": "好的，先不继续这个操作。你也可以继续看菜单或点餐。",
                "patch": {"last_recommendations": [], "pending_action": None},
            }
        return self.response_agent.fallback()

    def _contextual_item_modifier_interpretation(
        self,
        interpretation: Interpretation,
        compact: str,
        state: SessionState,
    ) -> Interpretation | None:
        if self.semantic_router._looks_like_question(compact):
            return None
        if interpretation.intent == "context_reference_resolution":
            return None
        modifiers = self.semantic_router.extract_item_modifiers(compact)
        if not modifiers:
            return None
        mentioned_items = self.menu_service.find_items_in_text(compact)
        if modifiers.get("note_request") and len(modifiers) == 1:
            if mentioned_items:
                return self._context_clarification("missing_item_note_content", item_name=mentioned_items[-1].name)
            if not state.current_order:
                return None
            if len(state.current_order) > 1:
                return self._context_clarification("ambiguous_item_modifier_reference")
            return self._context_clarification("missing_item_note_content", item_name=state.current_order[0].name)
        if mentioned_items:
            item_name = mentioned_items[-1].name
            order_indexes = [index for index, item in enumerate(state.current_order) if item.name == item_name]
            if len(order_indexes) == 1:
                return Interpretation(
                    intent="update_item_option",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"item_name": item_name, "index": order_indexes[0]},
                    preferences={**interpretation.preferences, **modifiers},
                )
            if len(order_indexes) > 1:
                return self._context_clarification("ambiguous_item_modifier_reference", item_name=item_name)
            if interpretation.intent == "update_item_option" or (
                interpretation.intent in {"fallback", "ask_recommendation_by_preference"}
                and any(token in compact for token in ["改成", "改为", "备注改成", "备注改为", "可以放", "不用"])
            ):
                return self._context_clarification("item_modifier_target_not_found", item_name=item_name)
            return None

        if not state.current_order:
            return None
        if len(state.current_order) > 1:
            return self._context_clarification("ambiguous_item_modifier_reference")
        return Interpretation(
            intent="update_item_option",
            confidence=0.9,
            source="merged",
            should_mutate_order=True,
            entities={"item_name": state.current_order[0].name, "index": 0},
            preferences={**interpretation.preferences, **modifiers},
        )

    def _handle_composite(self, interpretation: Interpretation, state: SessionState) -> dict:
        child_summaries: list[dict[str, Any]] = []
        messages: list[str] = []
        for child in interpretation.entities.get("children", []):
            child_interpretation = Interpretation(
                intent=child["intent"],
                confidence=child.get("confidence", 0.9),
                source=child.get("source", "rule"),
                is_question=child.get("is_question", False),
                should_mutate_order=child.get("should_mutate_order", False),
                entities=child.get("entities", {}),
                preferences=child.get("preferences", {}),
                target=child.get("target"),
            )
            before_child = state.clone()
            result = self._dispatch(child_interpretation, state)
            rejected = self._validate_state_patch(child_interpretation.intent, result.get("patch", {}), state)
            allowed = rejected is None
            if allowed:
                self._apply_patch(state, result.get("patch", {}))
            messages.append(result.get("message", ""))
            child_summaries.append(
                {
                    "intent": child_interpretation.intent,
                    "selectedAgent": result.get("agent"),
                    "selectedHandler": result.get("handler"),
                    "stateMutationAllowed": allowed,
                    "stateMutationRejectedReason": rejected,
                    "orderBefore": order_to_dicts(before_child.current_order),
                    "orderAfter": order_to_dicts(state.current_order),
                    "officialAddressBefore": before_child.official_delivery_address,
                    "officialAddressAfter": state.official_delivery_address,
                    "pendingCandidateBefore": dump_model(before_child.pending_delivery_address_candidate),
                    "pendingCandidateAfter": dump_model(state.pending_delivery_address_candidate),
                    "response": result.get("message", ""),
                }
            )
        return {
            "agent": "OrchestratorAgent",
            "handler": "composite_intent",
            "message": " ".join(message for message in messages if message),
            "patch": {},
            "compositeChildren": child_summaries,
        }

    def _handle_conditional_order(self, interpretation: Interpretation) -> dict:
        decision = interpretation.entities.get("conditionalDecision", {})
        fact = decision.get("fact_result", {})
        item_name = fact.get("item_name", "这个菜")
        if "price" in fact:
            condition = decision.get("condition", {})
            threshold = condition.get("threshold")
            outcome = f"{item_name} {fact['price']} 元"
            if threshold:
                outcome += f"，在 {threshold} 元以内" if fact.get("within_threshold") else f"，超过 {threshold} 元"
            message = outcome + "。要加入订单吗？"
        elif "supports" in fact:
            message = f"{item_name}{'支持' if fact.get('supports') else '不支持'}不辣。要按这个条件加入吗？"
        else:
            message = f"我查到{item_name}的信息了，要加入订单吗？"
        pending_action = {
            "type": "conditional_order",
            "condition": decision.get("condition"),
            "fact_result": decision.get("fact_result"),
            "proposed_action": decision.get("proposed_action"),
            "requires_confirmation": decision.get("requires_confirmation", True),
        }
        return {
            "agent": "OrchestratorAgent",
            "handler": "conditional_order",
            "message": message,
            "patch": {"pending_action": pending_action, "last_question_intent": "conditional_order"},
        }

    def _expire_stale_pending_state(self, interpretation: Interpretation, state: SessionState) -> None:
        patch: dict[str, Any] = {}
        if self._should_expire_pending_action(interpretation, state):
            patch["pending_action"] = None
        if self._should_expire_delivery_candidate(interpretation, state):
            patch["pending_delivery_address_candidate"] = None
        if patch:
            self._apply_patch(state, patch)

    def _should_expire_pending_action(self, interpretation: Interpretation, state: SessionState) -> bool:
        pending = state.pending_action
        if not pending:
            return False
        intent = interpretation.intent
        if intent in PENDING_ACTION_CONFIRM_INTENTS or intent in PENDING_ACTION_CANCEL_INTENTS:
            return False
        action_type = pending.get("type")
        if action_type == "confirm_clear_order":
            return intent in NO_MUTATION_INTENTS or intent == "fallback" or intent.startswith("ask_recommendation")
        if action_type in {"confirm_order_category_items", "confirm_remove_category_items", "conditional_order"}:
            return True
        return False

    def _should_expire_delivery_candidate(self, interpretation: Interpretation, state: SessionState) -> bool:
        if not state.pending_delivery_address_candidate:
            return False
        return interpretation.intent not in ADDRESS_CANDIDATE_LIVE_INTENTS

    def _validate_state_patch(self, intent: str, patch: dict[str, Any], state: SessionState) -> str | None:
        if intent not in NO_MUTATION_INTENTS:
            return None
        protected = ["current_order", "official_delivery_address", "phone"]
        for key in protected:
            if key not in patch:
                continue
            current = dump_model(getattr(state, key)) if key != "current_order" else order_to_dicts(state.current_order)
            proposed = self._serialize_patch_value(patch[key])
            if proposed != current:
                return f"{intent} cannot modify {key}"
        return None

    def _apply_patch(self, state: SessionState, patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if key == "current_order":
                state.current_order = [item if isinstance(item, OrderItem) else OrderItem(**item) for item in value]
            elif key == "pending_delivery_address_candidate":
                if value is None or isinstance(value, DeliveryAddressCandidate):
                    state.pending_delivery_address_candidate = value
                else:
                    state.pending_delivery_address_candidate = DeliveryAddressCandidate(**value)
            else:
                setattr(state, key, value)

    def _record_mutation_snapshot(
        self,
        state: SessionState,
        before: SessionState,
        after: SessionState,
        user_message: str,
        agent_action: str,
        confirmed: bool,
    ) -> None:
        fields = ["current_order", "official_delivery_address", "phone", "submitted", "submitted_order_id"]
        changed_fields = []
        before_data: dict[str, Any] = {}
        after_data: dict[str, Any] = {}
        for field in fields:
            before_value = order_to_dicts(before.current_order) if field == "current_order" else self._serialize_patch_value(getattr(before, field))
            after_value = order_to_dicts(after.current_order) if field == "current_order" else self._serialize_patch_value(getattr(after, field))
            if before_value != after_value:
                changed_fields.append(field)
                before_data[field] = before_value
                after_data[field] = after_value
        if not changed_fields:
            return
        if (
            "current_order" in changed_fields
            and before.current_order
            and not after.current_order
        ):
            state.last_mutation_snapshot = None
            state.last_mutation_confirmed = False
            return
        mutation_id = f"mutation-{id(state)}-{len(changed_fields)}"
        state.last_mutation_snapshot = {
            "mutation_id": mutation_id,
            "trigger_user_message": user_message,
            "agent_action": agent_action,
            "changed_fields": changed_fields,
            "before": before_data,
            "after": after_data,
            "confirmed": confirmed,
        }
        state.last_mutation_confirmed = confirmed

    def _maybe_apply_rollback(self, normalized: str, state: SessionState) -> tuple[bool, str | None, list[str]]:
        if not any(token in normalized for token in [
            "我只是问一下", "你别乱加", "我没说要点",
            "我没点", "没让你加", "加错了", "不对", "不是这个", "不是我要的",
            "弄错了", "搞错了", "误会了", "我只是问问", "我不是要点", "我只是想问",
            "我没说要", "我没想点", "我不是要这个",
        ]):
            return False, None, []
        snapshot = state.last_mutation_snapshot
        if not snapshot or snapshot.get("confirmed"):
            return False, "no_unconfirmed_mutation", []
        before_values = snapshot.get("before", {})
        fields = [field for field in snapshot.get("changed_fields", []) if field in before_values]
        if not fields:
            return False, "no_rollback_fields", []
        patch = {field: before_values[field] for field in fields}
        self._apply_patch(state, patch)
        state.last_mutation_snapshot = None
        state.last_mutation_confirmed = False
        state.pending_action = None
        return True, "rolled_back_recent_unconfirmed_mutation", fields

    def _serialize_patch_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return [dump_model(item) if hasattr(item, "dict") or hasattr(item, "model_dump") else item for item in value]
        if hasattr(value, "dict") or hasattr(value, "model_dump"):
            return dump_model(value)
        return value

    def _copy_interpretation(self, interpretation: Interpretation, update: dict[str, Any]) -> Interpretation:
        if hasattr(interpretation, "model_copy"):
            return interpretation.model_copy(update=update)
        return interpretation.copy(update=update)

    def _reference_to_index(self, reference: str) -> int | None:
        normalized = normalize_recommendation_ordinal_reference(reference)
        if normalized is not None:
            return normalized
        if match := re.search(r"第(\d+)[个份项]", reference):
            return int(match.group(1)) - 1
        if reference in {"第一个", "第1个", "第一份", "第1份", "第一项", "第1项", "推荐的第一个", "推荐的第1个", "刚推荐的第一个", "刚推荐的第1个", "订单里第一个", "订单里第1个", "已点的第一个", "已点的第1个"}:
            return 0
        if reference in {"第二个", "第2个", "第二份", "第2份", "第二项", "第2项"}:
            return 1
        if reference in {"第三个", "第3个", "第三份", "第3份", "第三项", "第3项"}:
            return 2
        return None

    def _recent_order_index(self, state: SessionState) -> int:
        if state.last_mentioned_item:
            for index in range(len(state.current_order) - 1, -1, -1):
                if state.current_order[index].name == state.last_mentioned_item:
                    return index
        return len(state.current_order) - 1

    def _unique_recent_order_index(self, state: SessionState) -> int | None:
        if not state.current_order:
            return None
        if state.last_mentioned_item:
            matches = [index for index, item in enumerate(state.current_order) if item.name == state.last_mentioned_item]
            if len(matches) == 1:
                return matches[0]
        if len(state.current_order) == 1:
            return 0
        return None

    def _has_option_change(self, text: str) -> bool:
        return any(
            token in text
            for token in [
                "不要辣",
                "不辣",
                "少辣",
                "微辣",
                "中辣",
                "特辣",
                "大份",
                "小份",
                "不要香菜",
                "不香菜",
                "不要葱",
                "不葱",
                "不要蒜",
                "不要辣椒",
                "不要花生",
                "不要洋葱",
                "香菜可以放",
                "备注",
                "米饭多一点",
                "汤分开放",
                "少放盐",
                "打包严实",
                "去冰",
                "少冰",
                "加蛋",
                "加青菜",
            ]
        )

    def _resolve_dish_fragment(self, raw_text: str) -> "tuple":
        """Extract dish name fragment from context reference and match to menu.

        e.g. '黑椒那个' -> '黑椒' -> matches '黑椒牛肉饭' uniquely.
        Returns (unique_item, all_matches) where:
        - unique_item is a MenuItem if exactly one match, else None
        - all_matches is the list of all matching item dicts (may be empty)
        """
        import re
        fragment = re.sub(
            r"(推荐的第一个|推荐的第1个|刚推荐的第一个|刚推荐的第1个|订单里第一个|订单里第1个|已点的第一个|已点的第1个|这个|那个|这份|那份|这些|那些|第一个|第1个|第二个|第2个|第三个|第3个|第一份|第1份|第二份|第2份|第三份|第3份|第一项|第1项|第二项|第2项|第三项|第3项|刚才那个|刚才的|刚加的)",
            "",
            raw_text,
        ).strip()
        if len(fragment) < 2:
            return None, []
        matches: list[dict] = []
        for item_dict in self.menu_service.all_items_as_dicts():
            name = item_dict.get("name", "")
            aliases = item_dict.get("aliases", [])
            for n in [name, *aliases]:
                if n and len(n) >= 2 and fragment in n:
                    matches.append(item_dict)
                    break
        if len(matches) == 1:
            return self.menu_service.find_item_by_name(matches[0]["name"]), matches
        return None, matches

    def _resolve_fragment_in_candidates(self, text: str, candidates: list[dict]) -> str | None:
        """Try to uniquely match text (which may contain a dish fragment + reference token)
        against the candidate list. Returns the candidate name if unique, else None."""
        import re
        fragment = re.sub(
            r"(推荐的第一个|推荐的第1个|刚推荐的第一个|刚推荐的第1个|订单里第一个|订单里第1个|已点的第一个|已点的第1个|这个|那个|这份|那份|这些|那些|第一个|第1个|第二个|第2个|第三个|第3个|第一份|第1份|第二份|第2份|第三份|第3份|第一项|第1项|第二项|第2项|第三项|第3项|刚才那个|刚才的|刚加的)",
            "",
            text,
        ).strip()
        if len(fragment) < 2:
            return None
        matches = [c["name"] for c in candidates if fragment in c["name"]]
        if len(matches) == 1:
            return matches[0]
        return None

    def _looks_like_address(self, text: str) -> bool:
        if not text:
            return False
        if any(token in text for token in ["有啥", "喝", "菜单", "多少钱", "配送费", "多久", "确认", "不用"]):
            return False
        return any(
            token in text
            for token in [
                "大学",
                "校区",
                "校园",
                "小区",
                "宿舍",
                "楼",
                "楼上",
                "楼下",
                "栋",
                "单元",
                "室",
                "号",
                "路",
                "街",
                "巷",
                "学院",
                "公司",
                "园区",
                "地铁站",
                "饭店",
                "餐厅",
                "饭堂",
                "旁边",
                "附近",
                "门口",
                "对面",
                "学校",
            ]
        )
