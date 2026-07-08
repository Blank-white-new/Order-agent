from __future__ import annotations

import re
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.state.session_state import SessionState


ReferenceDomain = Literal["recommendation", "order", "ambiguous", "none"]

ADD_ACTION_TOKENS = (
    "来一份",
    "来一个",
    "来一瓶",
    "来一杯",
    "来份",
    "来个",
    "来瓶",
    "来杯",
    "再来",
    "再加",
    "加一份",
    "加一个",
    "加一瓶",
    "加一杯",
    "给我来",
    "帮我加",
    "我要",
    "想要",
    "要一份",
    "要一个",
    "要一瓶",
    "要一杯",
    "各来",
    "都来",
)
REMOVE_ACTION_TOKENS = ("不要了", "删掉", "删了", "删除", "去掉", "拿掉", "移除", "清掉")
REPLACE_ACTION_TOKENS = ("换成", "换为", "换")
QUANTITY_UPDATE_TOKENS = ("少一份", "少一", "减一份", "减一", "多一份")
NON_ORDERING_MARKERS = (
    "听起来",
    "看起来",
    "好像",
    "似乎",
    "感觉",
    "不错",
    "可以",
    "我看看",
    "先看看",
    "看看",
    "了解一下",
    "考虑一下",
)
QUESTION_MARKERS = (
    "?",
    "？",
    "吗",
    "什么",
    "多少",
    "多久",
    "有没有",
    "还有吗",
    "有优惠",
    "优惠吗",
    "辣吗",
    "能送",
)
OPTION_CHANGE_TOKENS = (
    "不要辣",
    "不辣",
    "少辣",
    "微辣",
    "中辣",
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
)
ORDER_DOMAIN_TOKENS = ("订单里", "已点", "点的", "第一份", "第二份", "第三份", "第一项", "第二项", "第三项")
RECOMMENDATION_DOMAIN_TOKENS = ("推荐的", "刚推荐", "推荐列表")
REFERENCE_TOKENS = (
    "第一个",
    "第1个",
    "第二个",
    "第2个",
    "第三个",
    "第3个",
    "第一份",
    "第1份",
    "第二份",
    "第2份",
    "第三份",
    "第3份",
    "第一项",
    "第1项",
    "第二项",
    "第2项",
    "第三项",
    "第3项",
    "这个",
    "那个",
    "那份",
    "这份",
    "刚才那个",
    "刚才的",
    "刚加的",
)


def compact_text(text: str | None) -> str:
    return re.sub(r"[\s，,。！？!?；;、：:]", "", text or "")


def has_add_action_evidence(text: str) -> bool:
    compact = compact_text(text)
    if not compact:
        return False
    if any(token in compact for token in ADD_ACTION_TOKENS):
        return True
    return bool(re.search(r"(?:\d+|[一二两俩三四五六七八九十]+)(?:份|分|个|瓶|杯|碗)", compact))


def has_remove_action_evidence(text: str) -> bool:
    compact = compact_text(text)
    if any(token in compact for token in REMOVE_ACTION_TOKENS):
        return True
    return "不要" in compact and not any(token in compact for token in OPTION_CHANGE_TOKENS)


def has_replace_action_evidence(text: str) -> bool:
    compact = compact_text(text)
    return any(token in compact for token in REPLACE_ACTION_TOKENS)


def has_quantity_update_evidence(text: str) -> bool:
    compact = compact_text(text)
    if any(token in compact for token in QUANTITY_UPDATE_TOKENS):
        return True
    return bool(re.search(r"(?:改成|改为|变成)(?:\d+|[一二两俩三四五六七八九十]+)(?:份|分|个|瓶|杯|碗)?", compact))


def has_option_change_evidence(text: str) -> bool:
    compact = compact_text(text)
    return any(token in compact for token in OPTION_CHANGE_TOKENS)


def has_reference_token(text: str) -> bool:
    compact = compact_text(text)
    return any(token in compact for token in REFERENCE_TOKENS) or bool(re.search(r"第\d+[个份项]", compact))


def is_question_about_item(text: str) -> bool:
    compact = compact_text(text)
    return any(marker in compact for marker in QUESTION_MARKERS)


def is_non_ordering_statement(text: str) -> bool:
    compact = compact_text(text)
    if not compact or is_question_about_item(compact) or has_add_action_evidence(compact):
        return False
    return any(marker in compact for marker in NON_ORDERING_MARKERS)


def detect_reference_domain(
    text: str,
    has_recommendations: bool,
    has_order_items: bool,
) -> ReferenceDomain:
    compact = compact_text(text)
    if not has_reference_token(compact):
        return "none"
    explicit_recommendation = any(token in compact for token in RECOMMENDATION_DOMAIN_TOKENS)
    explicit_order = any(token in compact for token in ORDER_DOMAIN_TOKENS)
    mutates_existing = (
        has_remove_action_evidence(compact)
        or has_replace_action_evidence(compact)
        or has_quantity_update_evidence(compact)
        or has_option_change_evidence(compact)
    )
    destructive_existing_action = (
        has_remove_action_evidence(compact)
        or has_replace_action_evidence(compact)
        or has_quantity_update_evidence(compact)
    )
    if explicit_recommendation:
        return "recommendation" if has_recommendations else "ambiguous"
    if explicit_order:
        return "order" if has_order_items else "ambiguous"
    if has_recommendations and not has_order_items:
        return "ambiguous" if destructive_existing_action else "recommendation"
    if mutates_existing:
        if has_order_items:
            return "order"
        return "ambiguous"
    if has_recommendations and has_order_items:
        return "recommendation"
    if has_recommendations:
        return "recommendation"
    if has_order_items:
        return "order"
    return "none"


def should_clarify_reference(text: str, state: "SessionState") -> bool:
    domain = detect_reference_domain(
        text,
        has_recommendations=bool(state.last_recommendations),
        has_order_items=bool(state.current_order),
    )
    return domain == "ambiguous"
