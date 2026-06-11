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
from app.agents.semantic_router import SemanticRouterAgent
from app.models.schemas import Interpretation, dump_model
from app.services.delivery_service import DeliveryService
from app.services.llm_client import LLMClient
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
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


class OrchestratorAgent:
    def __init__(self) -> None:
        self.menu_service = MenuService()
        self.delivery_service = DeliveryService()
        self.order_service = OrderService()
        self.semantic_router = SemanticRouterAgent(self.menu_service)
        self.llm_client = LLMClient()
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
        interpretation = self.semantic_router.interpret(user_message)
        interpretation = self._merge_llm_interpretation(user_message, interpretation)
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
        return {"response": response, "state": state.serializable(), "trace": trace, "raw_state": state}

    def _merge_llm_interpretation(self, message: str, interpretation: Interpretation) -> Interpretation:
        if interpretation.confidence >= 0.85 and interpretation.source in {"rule", "deterministic"}:
            return interpretation
        llm_result = self.llm_client.interpret(message)
        if not llm_result:
            return interpretation
        return interpretation

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

        if interpretation.intent == "order_food" and state.current_order:
            item_name = interpretation.entities.get("item_name")
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

    def _resolve_context_reference(self, interpretation: Interpretation, state: SessionState) -> Interpretation:
        if interpretation.intent != "context_reference_resolution":
            return interpretation
        raw = interpretation.entities.get("raw", "")
        ref = interpretation.entities.get("reference", "")

        unique_item, all_matches = self._resolve_dish_fragment(raw)
        if unique_item:
            return Interpretation(
                intent="order_food",
                confidence=0.9,
                source="merged",
                should_mutate_order=True,
                entities={"item_name": unique_item.name, "quantity": 1},
                preferences=interpretation.preferences,
            )
        if all_matches and len(all_matches) > 1:
            names = [item["name"] for item in all_matches]
            return Interpretation(
                intent="context_correction",
                confidence=0.85,
                source="merged",
                should_mutate_order=False,
                entities={"candidates": names, "clarification": "ambiguous_dish_fragment"},
            )

        if raw in {"就那个", "要那个", "来那个"}:
            rec_names = None
            if state.last_recommendations:
                rec_names = [rec["name"] for rec in state.last_recommendations[:3]]
            elif state.viewed_category:
                items = self.menu_service.get_available_items_by_category(state.viewed_category)
                rec_names = [item.name for item in items[:4]]
            if rec_names:
                return Interpretation(
                    intent="context_correction",
                    confidence=0.85,
                    source="merged",
                    should_mutate_order=False,
                    entities={
                        "candidates": rec_names,
                        "clarification": "ambiguous_no_dish_fragment",
                    },
                )

        index = self._reference_to_index(ref)
        if state.current_order and self._has_option_change(raw) and ref in {"这个", "那个", "刚才那个"}:
            resolved_index = self._recent_order_index(state)
            return Interpretation(
                intent="update_item_option",
                confidence=0.9,
                source="merged",
                should_mutate_order=True,
                entities={"index": resolved_index, "item_name": state.current_order[resolved_index].name},
                preferences=interpretation.preferences,
            )
        if state.last_recommendations and (index is not None or raw in {"就这个", "要这个", "这些都要"}):
            resolved_index = 0 if index is None else index
            return Interpretation(
                intent="select_recommendation",
                confidence=0.92,
                source="merged",
                should_mutate_order=True,
                entities={"index": resolved_index},
                preferences=interpretation.preferences,
            )
        if state.current_order and index is not None:
            if "不要了" in raw:
                return Interpretation(
                    intent="remove_item",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"index": index, "item_name": state.current_order[index].name if index < len(state.current_order) else ""},
                )
            if any(token in raw for token in ["不辣", "不要辣", "大份", "小份"]):
                return Interpretation(
                    intent="update_item_option",
                    confidence=0.9,
                    source="merged",
                    should_mutate_order=True,
                    entities={"index": index, "item_name": state.current_order[index].name if index < len(state.current_order) else ""},
                    preferences=interpretation.preferences,
                )
        return Interpretation(
            intent="context_correction",
            confidence=0.75,
            source="merged",
            should_mutate_order=False,
            entities={"clarification": "reference_unresolved"},
        )

    def _dispatch(self, interpretation: Interpretation, state: SessionState) -> dict:
        intent = interpretation.intent
        if intent == "cancel_ambiguous_selection":
            return {
                "agent": "ResponseAgent",
                "handler": "cancel_ambiguous_selection",
                "message": "好的，先不选这个。你可以继续点菜或看菜单。",
                "patch": {"pending_action": None},
            }
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
        if reference in {"第一个"}:
            return 0
        if reference == "第二个":
            return 1
        if reference == "第三个":
            return 2
        if reference == "刚才那个":
            return 0
        return None

    def _recent_order_index(self, state: SessionState) -> int:
        if state.last_mentioned_item:
            for index in range(len(state.current_order) - 1, -1, -1):
                if state.current_order[index].name == state.last_mentioned_item:
                    return index
        return len(state.current_order) - 1

    def _has_option_change(self, text: str) -> bool:
        return any(
            token in text
            for token in [
                "不要辣",
                "不辣",
                "少辣",
                "微辣",
                "大份",
                "小份",
                "不要香菜",
                "不香菜",
                "不要葱",
                "不葱",
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
        fragment = re.sub(r"(这个|那个|这些|那些|第一个|第二个|第三个|刚才那个)", "", raw_text).strip()
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
        fragment = re.sub(r"(这个|那个|这些|那些|第一个|第二个|第三个|刚才那个)", "", text).strip()
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
        return any(token in text for token in ["大学", "校区", "校园", "门", "路", "街", "号", "宿舍", "楼", "学校"])
