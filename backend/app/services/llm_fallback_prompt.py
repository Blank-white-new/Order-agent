from __future__ import annotations

import difflib
import json
import re
from typing import Any

from app.services.menu_service import MenuService
from app.state.session_state import SessionState
from app.voice.transcript_normalizer import normalize_ordering_voice_transcript


SYSTEM_PROMPT = """你是订餐系统的意图解析器。你的任务是把用户输入解析成结构化 JSON。
只能基于提供的候选菜单、当前订单摘要和上下文。不要编造菜单项，不要编造价格。
不要输出 Markdown，不要输出解释，只输出 JSON object。不确定时输出 clarify，不要猜。
如果用户说“这个/那个/刚才那个”，只有上下文唯一明确时才能解析，否则澄清。"""

PHONE_RE = re.compile(r"1[3-9]\d{9}")
ADDRESS_TOKENS = ("地址", "校区", "校园", "大学", "宿舍", "楼", "街", "路", "号", "门", "小区", "公寓")
ASR_HINTS = {
    "黑胶牛肉饭": "黑椒牛肉饭",
    "黑角牛肉饭": "黑椒牛肉饭",
    "牛肉反": "牛肉饭",
    "机腿饭": "鸡腿饭",
}


def build_llm_fallback_prompt(
    user_message: str,
    state: SessionState,
    menu_service: MenuService,
    *,
    top_n: int = 8,
) -> str:
    candidates = recall_menu_candidates(user_message, menu_service, limit=top_n)
    context = {
        "task": "Parse the user's ordering intent into the required JSON object.",
        "schema": {
            "intent": "add_item | remove_item | update_quantity | ask_menu | ask_recommendation | delivery | pickup | confirm_order | cancel_order | clarify | smalltalk | unknown",
            "confidence": "number from 0 to 1",
            "normalized_text": "string or null",
            "actions": [
                {
                    "type": "add_item | remove_item | update_quantity | set_delivery | set_pickup | ask_menu | ask_recommendation | confirm_order | cancel_order",
                    "item_name": "must be from candidate_menu_items or null",
                    "quantity": "integer 1 to 20 or null",
                    "options": {},
                    "target": "string or null",
                }
            ],
            "needs_clarification": "boolean",
            "clarification_question": "string or null",
            "user_facing_reply": "string or null",
        },
        "privacy_rules": [
            "Do not infer or repeat hidden phone/address details.",
            "Do not create menu items or prices.",
            "Do not bypass confirmation.",
        ],
        "current_user_input": sanitize_user_text(user_message),
        "address_present": bool(state.official_delivery_address or state.pending_delivery_address_candidate),
        "phone_present": bool(state.phone),
        "pending_question": sanitize_short_text(state.pending_question),
        "pending_action_type": _pending_action_type(state),
        "order_summary": _order_summary(state),
        "last_recommendations": _last_recommendation_names(state),
        "recent_summary": _recent_summary(state),
        "candidate_menu_items": [
            {
                "name": item["name"],
                "category": item["category"],
                "aliases": item.get("aliases", [])[:3],
                "available": item.get("available", True),
            }
            for item in candidates
        ],
    }
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))


def recall_menu_candidates(user_message: str, menu_service: MenuService, *, limit: int = 8) -> list[dict[str, Any]]:
    items = menu_service.all_items_as_dicts()
    menu_names = [item["name"] for item in items]
    normalized = normalize_ordering_voice_transcript(user_message, menu_items=menu_names).normalized_text
    text = _compact(user_message)
    normalized_text = _compact(normalized)
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(items):
        names = [item["name"], *item.get("aliases", [])]
        score = _candidate_score(text, normalized_text, names)
        if score > 0:
            ranked.append((score, -index, item))
    if not ranked:
        ranked = _fuzzy_candidates(normalized_text or text, items)
    if not ranked:
        ranked = [(1, -index, item) for index, item in enumerate(items[:limit])]
    ordered = [entry[2] for entry in sorted(ranked, key=lambda entry: (-entry[0], -entry[1]))]
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ordered:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def sanitize_user_text(text: str | None, *, limit: int = 80) -> str:
    value = sanitize_short_text(text, limit=limit)
    value = PHONE_RE.sub("[phone]", value)
    if _looks_like_address(value):
        return "[address-related message hidden]"
    return value


def sanitize_short_text(text: str | None, *, limit: int = 80) -> str | None:
    if not text:
        return None
    value = str(text).strip()
    if len(value) > limit:
        value = f"{value[:limit]}..."
    return value


def _candidate_score(text: str, normalized_text: str, names: list[str]) -> int:
    score = 0
    for name in names:
        compact_name = _compact(name)
        if not compact_name:
            continue
        if compact_name == text or compact_name == normalized_text:
            score = max(score, 100)
        if compact_name in text or compact_name in normalized_text:
            score = max(score, 80 + len(compact_name))
        for source, target in ASR_HINTS.items():
            if target == name and source in text:
                score = max(score, 90)
    return score


def _fuzzy_candidates(text: str, items: list[dict[str, Any]]) -> list[tuple[int, int, dict[str, Any]]]:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    if len(text) < 3:
        return ranked
    for index, item in enumerate(items):
        names = [item["name"], *item.get("aliases", [])]
        best = 0.0
        for name in names:
            compact_name = _compact(name)
            if len(compact_name) < 3:
                continue
            for span in _candidate_spans(text, len(compact_name)):
                best = max(best, difflib.SequenceMatcher(a=span, b=compact_name).ratio())
        if best >= 0.72:
            ranked.append((int(best * 70), -index, item))
    return ranked


def _candidate_spans(text: str, target_len: int) -> list[str]:
    spans: list[str] = []
    for length in range(max(3, target_len - 1), min(len(text), target_len + 1) + 1):
        for start in range(0, len(text) - length + 1):
            span = text[start : start + length]
            if any(ch in span for ch in "我要来加再点份个瓶杯，,。！？!?；; "):
                continue
            spans.append(span)
    return spans


def _compact(text: str | None) -> str:
    return re.sub(r"[\s，,。！？!?；;、：:\"'“”‘’（）()【】\[\].…-]+", "", text or "")


def _looks_like_address(text: str) -> bool:
    return any(token in text for token in ADDRESS_TOKENS)


def _pending_action_type(state: SessionState) -> str | None:
    if not state.pending_action:
        return None
    action_type = state.pending_action.get("type")
    return str(action_type) if action_type else None


def _order_summary(state: SessionState) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "quantity": item.quantity,
            "options": item.options[:5],
            "category": item.category,
        }
        for item in state.current_order
    ]


def _last_recommendation_names(state: SessionState) -> list[str]:
    return [str(item.get("name")) for item in state.last_recommendations[:5] if item.get("name")]


def _recent_summary(state: SessionState) -> list[str]:
    summary: list[str] = [f"stage={state.stage}", f"fulfillment_type={state.fulfillment_type}"]
    if state.last_mentioned_item:
        summary.append(f"last_mentioned_item={state.last_mentioned_item}")
    if state.viewed_category:
        summary.append(f"viewed_category={state.viewed_category}")
    if state.viewed_category_group:
        summary.append(f"viewed_category_group={state.viewed_category_group}")
    return summary[:5]
