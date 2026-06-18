from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.models.schemas import Interpretation
from app.services.llm_fallback_schemas import (
    ALLOWED_LLM_ACTION_TYPES,
    ALLOWED_LLM_INTENTS,
    LLMFallbackAction,
    LLMFallbackInterpretation,
)
from app.services.menu_service import MenuService
from app.state.session_state import SessionState
from app.voice.transcript_normalizer import normalize_ordering_voice_transcript


EXPLICIT_CONFIRM_WORDS = ("确认", "下单", "提交订单", "就这样", "就这些", "可以下单")
EXPLICIT_CANCEL_WORDS = ("取消", "算了", "不要了", "不点了", "先不要")
ORDER_ACTION_TOKENS = (
    "来一份",
    "来个",
    "来一",
    "再来",
    "再加",
    "点",
    "加",
    "换成",
    "改成",
    "order",
    "add",
    "want",
    "give me",
)
ADDRESS_TOKENS = (
    "地址",
    "校区",
    "校园",
    "大学",
    "宿舍",
    "楼",
    "街",
    "路",
    "号",
    "门",
    "小区",
    "公寓",
    "饭堂",
    "餐厅",
    "饭店",
    "旁边",
    "楼上",
    "楼下",
)
REFERENCE_INDEXES = {
    "第一个": 0,
    "第1个": 0,
    "一": 0,
    "1": 0,
    "第二个": 1,
    "第2个": 1,
    "二": 1,
    "2": 1,
    "第三个": 2,
    "第3个": 2,
    "三": 2,
    "3": 2,
}
GENERIC_REFERENCE_TOKENS = ("这个", "那个", "刚才那个", "就这个", "就那个", "要这个", "要那个", "来这个", "来那个")
ADDRESS_PLACE_SUFFIXES = ("店", "饭店", "餐厅", "饭堂", "楼", "楼上", "楼下", "旁边", "附近", "门口", "对面")
UNSAFE_REPLY_PATTERNS = (
    re.compile(r"\d+\s*元"),
    re.compile(r"已\s*(下单|提交)"),
    re.compile(r"订单已"),
)


@dataclass
class LLMFallbackValidationResult:
    ok: bool
    reason: str | None = None
    parsed: LLMFallbackInterpretation | None = None
    interpretation: Interpretation | None = None
    safe_reply: str | None = None


def parse_llm_fallback_payload(payload: dict[str, Any]) -> LLMFallbackValidationResult:
    try:
        parsed = LLMFallbackInterpretation(**payload)
    except (TypeError, ValidationError, ValueError):
        return LLMFallbackValidationResult(ok=False, reason="schema_error")
    if parsed.intent not in ALLOWED_LLM_INTENTS:
        return LLMFallbackValidationResult(ok=False, reason="intent_not_allowed", parsed=parsed)
    if not 0 <= parsed.confidence <= 1:
        return LLMFallbackValidationResult(ok=False, reason="confidence_out_of_range", parsed=parsed)
    if len(parsed.actions) > 3:
        return LLMFallbackValidationResult(ok=False, reason="too_many_actions", parsed=parsed)
    for action in parsed.actions:
        if action.type not in ALLOWED_LLM_ACTION_TYPES:
            return LLMFallbackValidationResult(ok=False, reason="action_not_allowed", parsed=parsed)
        if action.quantity is not None and not 1 <= int(action.quantity) <= 20:
            return LLMFallbackValidationResult(ok=False, reason="quantity_out_of_range", parsed=parsed)
    return LLMFallbackValidationResult(ok=True, parsed=parsed)


def convert_llm_to_interpretation(
    parsed: LLMFallbackInterpretation,
    *,
    original_message: str,
    menu_service: MenuService,
    state: SessionState,
    min_confidence: float,
) -> LLMFallbackValidationResult:
    if parsed.confidence < min_confidence:
        return LLMFallbackValidationResult(ok=False, reason="low_confidence", parsed=parsed)
    if parsed.needs_clarification or parsed.intent in {"clarify", "unknown", "smalltalk"}:
        return LLMFallbackValidationResult(
            ok=True,
            parsed=parsed,
            interpretation=_fallback_interpretation(parsed, directed_message=None),
            safe_reply=_safe_candidate_reply(parsed, menu_service),
        )

    if len(parsed.actions) > 1:
        return LLMFallbackValidationResult(ok=False, reason="multi_action_not_supported", parsed=parsed)

    action = parsed.actions[0] if parsed.actions else _implicit_action(parsed)
    if action is None:
        return LLMFallbackValidationResult(ok=False, reason="missing_action", parsed=parsed)

    if parsed.intent == "add_item" or action.type == "add_item":
        return _convert_add_item(parsed, action, menu_service, original_message=original_message, state=state)
    if parsed.intent == "ask_menu" or action.type == "ask_menu":
        return _converted(parsed, Interpretation(intent="ask_menu", confidence=parsed.confidence, source="llm", is_question=True))
    if parsed.intent == "ask_recommendation" or action.type == "ask_recommendation":
        return _converted(parsed, Interpretation(intent="ask_recommendation", confidence=parsed.confidence, source="llm", is_question=True))
    if parsed.intent == "delivery" or action.type == "set_delivery":
        return _converted(
            parsed,
            Interpretation(
                intent="provide_fulfillment_slot",
                confidence=parsed.confidence,
                source="llm",
                should_mutate_order=True,
                entities={"fulfillment_type": "delivery"},
            ),
        )
    if parsed.intent == "pickup" or action.type == "set_pickup":
        return _converted(
            parsed,
            Interpretation(
                intent="provide_fulfillment_slot",
                confidence=parsed.confidence,
                source="llm",
                should_mutate_order=True,
                entities={"fulfillment_type": "pickup"},
            ),
        )
    if parsed.intent == "confirm_order" or action.type == "confirm_order":
        if not _has_explicit_confirm(original_message):
            return LLMFallbackValidationResult(ok=False, reason="confirm_requires_explicit_user_confirmation", parsed=parsed)
        return _converted(parsed, Interpretation(intent="confirm", confidence=parsed.confidence, source="llm", should_mutate_order=False))
    if parsed.intent == "cancel_order" or action.type == "cancel_order":
        if not _has_explicit_cancel(original_message):
            return LLMFallbackValidationResult(ok=False, reason="cancel_requires_explicit_user_cancellation", parsed=parsed)
        return _converted(parsed, Interpretation(intent="cancel", confidence=parsed.confidence, source="llm", should_mutate_order=False))

    return LLMFallbackValidationResult(ok=False, reason="unsafe_action_not_supported", parsed=parsed)


def build_directed_clarification(message: str, state: SessionState, reason: str | None = None) -> str:
    text = message or ""
    if any(token in text for token in ["便宜", "贵", "换"]):
        if state.current_order:
            return "你是想把当前订单里的某个菜换成更便宜的，还是想让我推荐便宜一些的菜？"
        return "你是想让我推荐便宜一些的菜，还是想先看看菜单价格？"
    if any(token in text for token in ["那个", "这个", "刚才"]):
        return "你说的“那个”是指刚才推荐的菜，还是当前订单里的菜？"
    if any(token in text for token in ["配送", "外卖", "送"]):
        if not state.official_delivery_address:
            return "请告诉我配送地址。"
        if not state.phone:
            return "配送地址已有了，请告诉我联系电话。"
        return "配送信息已有了，你要继续确认订单还是修改配送信息？"
    if any(token in text for token in ["确认", "下单", "提交"]):
        return "确认前我需要先核对菜品、配送或自取方式，以及联系电话。"
    if reason in {"invalid_json", "schema_error", "timeout"}:
        return "你是想点菜、看菜单、改订单，还是安排配送？"
    return "你是想点菜、看菜单、问配送，还是修改订单？"


def has_explicit_order_action(text: str | None) -> bool:
    normalized = _compact(text)
    lowered = (text or "").lower()
    if not normalized and not lowered:
        return False
    if re.search(r"\b(?:order|add|want)\b|give me", lowered):
        return True
    if any(token in normalized for token in ORDER_ACTION_TOKENS):
        return True
    if "不要" not in normalized and re.search(r"(?:要|想要|我要)(?!送|配送|多久|地址)", normalized):
        return True
    return False


def _convert_add_item(
    parsed: LLMFallbackInterpretation,
    action: LLMFallbackAction,
    menu_service: MenuService,
    *,
    original_message: str,
    state: SessionState,
) -> LLMFallbackValidationResult:
    item_name = action.item_name
    item = menu_service.find_item_by_name(item_name)
    if not item:
        return LLMFallbackValidationResult(ok=False, reason="menu_item_not_found", parsed=parsed)
    if not _has_add_item_evidence(original_message, item.name, menu_service, state):
        return LLMFallbackValidationResult(ok=False, reason="llm_order_action_requires_target_item_evidence", parsed=parsed)
    options = _extract_options(action)
    interpretation = Interpretation(
        intent="order_food",
        confidence=parsed.confidence,
        source="llm",
        should_mutate_order=True,
        entities={"item_name": item.name, "quantity": action.quantity or 1},
        preferences={"options": options} if options else {},
    )
    return _converted(parsed, interpretation)


def _converted(parsed: LLMFallbackInterpretation, interpretation: Interpretation) -> LLMFallbackValidationResult:
    return LLMFallbackValidationResult(ok=True, parsed=parsed, interpretation=interpretation)


def _fallback_interpretation(parsed: LLMFallbackInterpretation, directed_message: str | None) -> Interpretation:
    entities = {"llm_clarification": True}
    if directed_message:
        entities["directed_message"] = directed_message
    return Interpretation(
        intent="fallback",
        confidence=parsed.confidence,
        source="llm",
        should_mutate_order=False,
        entities=entities,
    )


def _implicit_action(parsed: LLMFallbackInterpretation) -> LLMFallbackAction | None:
    mapping = {
        "ask_menu": "ask_menu",
        "ask_recommendation": "ask_recommendation",
        "delivery": "set_delivery",
        "pickup": "set_pickup",
        "confirm_order": "confirm_order",
        "cancel_order": "cancel_order",
    }
    action_type = mapping.get(parsed.intent)
    return LLMFallbackAction(type=action_type) if action_type else None


def _extract_options(action: LLMFallbackAction) -> list[str]:
    raw = action.options.get("options") if isinstance(action.options, dict) else None
    if isinstance(raw, list):
        return [str(option) for option in raw if option]
    return [str(value) for value in action.options.values() if isinstance(value, str) and value]


def _has_explicit_confirm(message: str) -> bool:
    return any(word in message for word in EXPLICIT_CONFIRM_WORDS)


def _has_explicit_cancel(message: str) -> bool:
    return any(word in message for word in EXPLICIT_CANCEL_WORDS)


def _safe_candidate_reply(parsed: LLMFallbackInterpretation, menu_service: MenuService) -> str | None:
    candidate = parsed.clarification_question or parsed.user_facing_reply
    if not candidate:
        return None
    if len(candidate) > 80:
        return None
    if any(pattern.search(candidate) for pattern in UNSAFE_REPLY_PATTERNS):
        return None
    menu_names = {item["name"] for item in menu_service.all_items_as_dicts()}
    dish_like = re.findall(r"[\u4e00-\u9fff]{2,}(?:饭|面|小吃|可乐|雪碧|茶)", candidate)
    if any(name not in menu_names for name in dish_like):
        return None
    return candidate


def _has_add_item_evidence(
    original_message: str,
    target_item_name: str,
    menu_service: MenuService,
    state: SessionState,
) -> bool:
    text = _compact(original_message)
    normalized = _compact(_normalize_with_menu(original_message, menu_service, state))

    if _mentions_item(text, normalized, target_item_name, menu_service):
        return True
    if _has_unique_reference_to_item(text, target_item_name, state):
        return True
    return False


def _normalize_with_menu(message: str, menu_service: MenuService, state: SessionState) -> str:
    names = [item["name"] for item in menu_service.all_items_as_dicts()]
    context = {
        "stage": state.stage,
        "current_order_count": len(state.current_order),
        "viewed_category": state.viewed_category,
        "viewed_category_group": state.viewed_category_group,
        "last_mentioned_category": state.last_mentioned_category,
        "pending_question": state.pending_question,
        "last_question_intent": state.last_question_intent,
    }
    return normalize_ordering_voice_transcript(message, menu_items=names, context=context).normalized_text


def _mentions_item(text: str, normalized: str, target_item_name: str, menu_service: MenuService) -> bool:
    item = menu_service.find_item_by_name(target_item_name)
    if not item:
        return False
    names = [_compact(name) for name in menu_service.matching_names_for_item(item.name)]
    return any(_contains_menu_evidence(text, name) or _contains_menu_evidence(normalized, name) for name in names if name)


def _contains_menu_evidence(text: str, name: str) -> bool:
    start = text.find(name)
    while start >= 0:
        end = start + len(name)
        if not _is_embedded_in_address_place(text, end):
            return True
        start = text.find(name, start + 1)
    return False


def _is_embedded_in_address_place(text: str, end: int) -> bool:
    tail = text[end : end + 4]
    return any(tail.startswith(suffix) for suffix in ADDRESS_PLACE_SUFFIXES)


def _has_quantity_cue(text: str) -> bool:
    return bool(re.search(r"(?:\d+|[一二两俩三四五六七八九十]+)\s*(?:份|个|瓶|杯|碗|份儿)", text))


def _has_unique_reference_to_item(text: str, target_item_name: str, state: SessionState) -> bool:
    for token, index in REFERENCE_INDEXES.items():
        if text != token:
            continue
        if index < len(state.last_recommendations):
            return state.last_recommendations[index].get("name") == target_item_name
        return False

    if not any(token in text for token in GENERIC_REFERENCE_TOKENS):
        return False

    candidates: list[str] = []
    if state.last_mentioned_item:
        candidates.append(state.last_mentioned_item)
    if len(state.last_recommendations) == 1:
        candidates.append(str(state.last_recommendations[0].get("name")))
    if len(state.current_order) == 1:
        candidates.append(state.current_order[0].name)
    unique_candidates = {candidate for candidate in candidates if candidate}
    return len(unique_candidates) == 1 and target_item_name in unique_candidates


def _looks_like_address(text: str) -> bool:
    return any(token in text for token in ADDRESS_TOKENS)


def _compact(text: str | None) -> str:
    return re.sub(r"[\s，,。！？!?；;、：:\"'“”‘’（）()【】\[\].…-]+", "", text or "")
