from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from app.voice.text_cleaner import normalize_voice_transcript


@dataclass
class VoiceTranscriptNormalizationResult:
    original_text: str
    normalized_text: str
    changed: bool
    reasons: list[str] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0


CHINESE_NUMBERS = "一二两俩三四五六七八九十"
ORDER_CONTEXT_TOKENS = ("来", "要", "点", "加", "再来", "换成", "改成", "一份", "两份", "俩份", "份")
ADDRESS_TOKENS = ("地址", "校区", "校园", "大学", "宿舍", "楼", "街", "路", "号", "门")
PHONE_TOKENS = ("电话", "手机号", "手机", "号码", "联系")
PHONE_NUMBER_WORDS = "零一二两三四五六七八九十幺"
TASTE_NOTE_NEGATIVES = (
    "不要辣",
    "不要辣椒",
    "不要放辣椒",
    "不要太辣",
    "不要香菜",
    "不要葱",
    "不要姜",
    "不要蒜",
)

EXPLICIT_MENU_CORRECTIONS = (
    ("黑胶牛肉饭", "黑椒牛肉饭"),
    ("黑角牛肉饭", "黑椒牛肉饭"),
    ("牛肉反", "牛肉饭"),
    ("机腿饭", "鸡腿饭"),
)


def normalize_ordering_voice_transcript(
    transcript: str | None,
    *,
    menu_items: list[str] | None = None,
    context: dict | None = None,
) -> VoiceTranscriptNormalizationResult:
    original = normalize_voice_transcript(transcript)
    if not original or _is_punctuation_only(original):
        return _result(original, original)

    menu_words = _dedupe_words(menu_items)
    ctx = context or {}
    text = original
    reasons: list[str] = []
    corrections: list[dict[str, Any]] = []
    confidence = 1.0

    text, changed = _replace_once(text, "在来一份", "再来一份")
    if changed:
        _record(corrections, "在来一份", "再来一份", "action")
        reasons.append("action_common_asr")
        confidence = min(confidence, 0.94)

    text, changed = _replace_once(text, "再来亿份", "再来一份")
    if changed:
        _record(corrections, "再来亿份", "再来一份", "quantity_common_asr")
        reasons.append("quantity_common_asr")
        confidence = min(confidence, 0.94)

    if text == "确认一下":
        _record(corrections, text, "确认", "confirm")
        reasons.append("confirm_short_phrase")
        text = "确认"
        confidence = min(confidence, 0.95)
    elif text in {"可以了", "就这些"} and int(ctx.get("current_order_count") or 0) > 0:
        _record(corrections, text, "确认", "confirm_with_order")
        reasons.append("confirm_with_existing_order")
        text = "确认"
        confidence = min(confidence, 0.9)

    if text == "不要啦":
        _record(corrections, text, "不要了", "cancel")
        reasons.append("cancel_common_asr")
        text = "不要了"
        confidence = min(confidence, 0.94)

    text, changed = _replace_once(text, "陪送", "配送")
    if changed:
        _record(corrections, "陪送", "配送", "fulfillment")
        reasons.append("fulfillment_common_asr")
        confidence = min(confidence, 0.95)

    if text == "自己" and _is_fulfillment_context(ctx):
        _record(corrections, "自己", "自取", "fulfillment_context")
        reasons.append("pickup_context")
        text = "自取"
        confidence = min(confidence, 0.9)

    text, unit_corrections = _normalize_quantity_units(text, menu_words, ctx)
    if unit_corrections:
        corrections.extend(unit_corrections)
        reasons.append("quantity_unit_near_order_context")
        confidence = min(confidence, 0.92)

    if not _should_skip_menu_correction(text, ctx):
        text, menu_corrections, menu_confidence = _normalize_menu_words(text, menu_words, ctx)
        if menu_corrections:
            corrections.extend(menu_corrections)
            reasons.append("menu_item_correction")
            confidence = min(confidence, menu_confidence)

    return _result(original, text, reasons, corrections, confidence)


def _result(
    original_text: str,
    normalized_text: str,
    reasons: list[str] | None = None,
    corrections: list[dict[str, Any]] | None = None,
    confidence: float = 1.0,
) -> VoiceTranscriptNormalizationResult:
    changed = original_text != normalized_text
    return VoiceTranscriptNormalizationResult(
        original_text=original_text,
        normalized_text=normalized_text,
        changed=changed,
        reasons=reasons or [],
        corrections=corrections or [],
        confidence=confidence if changed else 1.0,
    )


def _dedupe_words(menu_items: list[str] | None) -> list[str]:
    words: list[str] = []
    for item in menu_items or []:
        word = normalize_voice_transcript(str(item))
        if word and word not in words:
            words.append(word)
    return words


def _is_punctuation_only(text: str) -> bool:
    compact = re.sub(r"[\s，,。！？!?；;、：:\"'“”‘’（）()【】\[\].…-]+", "", text)
    return compact == ""


def _replace_once(text: str, source: str, target: str) -> tuple[str, bool]:
    if source not in text:
        return text, False
    return text.replace(source, target, 1), True


def _record(corrections: list[dict[str, Any]], source: str, target: str, reason: str) -> None:
    corrections.append({"from": source, "to": target, "reason": reason})


def _normalize_quantity_units(text: str, menu_words: list[str], context: dict) -> tuple[str, list[dict[str, Any]]]:
    corrections: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if not _is_ordering_context(text, menu_words, context, match.start(), match.end()):
            return match.group(0)
        source = f"{token}分"
        target = f"{token}份"
        _record(corrections, source, target, "quantity_unit")
        return target

    normalized = re.sub(rf"([{CHINESE_NUMBERS}])分", replace, text)
    return normalized, corrections


def _is_ordering_context(text: str, menu_words: list[str], context: dict, start: int | None = None, end: int | None = None) -> bool:
    if (context.get("stage") or "ordering") in {"ordering", "confirming"} and any(token in text for token in ORDER_CONTEXT_TOKENS):
        return True
    if _contains_menu_word(text, menu_words):
        return True
    if start is not None and end is not None:
        window = text[max(0, start - 5) : min(len(text), end + 8)]
        if any(word and word in window for word in menu_words):
            return True
        if any(token in window for token in ORDER_CONTEXT_TOKENS):
            return True
    return False


def _contains_menu_word(text: str, menu_words: list[str]) -> bool:
    return any(word and word in text for word in menu_words)


def _normalize_menu_words(text: str, menu_words: list[str], context: dict) -> tuple[str, list[dict[str, Any]], float]:
    corrections: list[dict[str, Any]] = []
    menu_set = set(menu_words)
    normalized = text
    confidence = 1.0

    for source, target in EXPLICIT_MENU_CORRECTIONS:
        if source not in normalized or target not in menu_set:
            continue
        if source in menu_set:
            continue
        normalized = normalized.replace(source, target, 1)
        _record(corrections, source, target, "explicit_menu_asr")
        confidence = min(confidence, 0.96)

    if corrections or not _menu_fuzzy_allowed(normalized, menu_words, context):
        return normalized, corrections, confidence

    candidate = _best_fuzzy_menu_candidate(normalized, menu_words)
    if not candidate:
        return normalized, corrections, confidence

    source, target, ratio = candidate
    if source == target or target not in menu_set:
        return normalized, corrections, confidence
    normalized = normalized.replace(source, target, 1)
    _record(corrections, source, target, "fuzzy_menu_match")
    return normalized, corrections, min(confidence, ratio)


def _menu_fuzzy_allowed(text: str, menu_words: list[str], context: dict) -> bool:
    if not menu_words:
        return False
    if _contains_menu_word(text, menu_words):
        return False
    if _looks_like_address_or_phone(text):
        return False
    return _is_ordering_context(text, menu_words, context)


def _best_fuzzy_menu_candidate(text: str, menu_words: list[str]) -> tuple[str, str, float] | None:
    best: tuple[str, str, float] | None = None
    for target in menu_words:
        if len(target) < 3:
            continue
        for source in _candidate_spans(text, len(target)):
            if len(source) < 3 or source == target:
                continue
            ratio = difflib.SequenceMatcher(a=source, b=target).ratio()
            if ratio < 0.86:
                continue
            if best is None or ratio > best[2]:
                best = (source, target, ratio)
    return best


def _candidate_spans(text: str, target_len: int) -> list[str]:
    spans: list[str] = []
    min_len = max(3, target_len - 1)
    max_len = target_len + 1
    for length in range(min_len, max_len + 1):
        if length > len(text):
            continue
        for start in range(0, len(text) - length + 1):
            span = text[start : start + length]
            if _span_has_order_noise(span):
                continue
            spans.append(span)
    return spans


def _span_has_order_noise(span: str) -> bool:
    return any(ch in span for ch in "我要来加再点份个瓶杯，,。！？!?；; ")


def _should_skip_menu_correction(text: str, context: dict) -> bool:
    if any(text == note or text.startswith(note) for note in TASTE_NOTE_NEGATIVES):
        return True
    if "不想吃辣" in text:
        return True
    if _looks_like_address_or_phone(text):
        return not _explicit_menu_context(context)
    return False


def _looks_like_address_or_phone(text: str) -> bool:
    if any(token in text for token in PHONE_TOKENS):
        return True
    digits = re.findall(r"\d", text)
    number_words = [ch for ch in text if ch in PHONE_NUMBER_WORDS]
    if len(digits) >= 7 or len(number_words) >= 8:
        return True
    if any(token in text for token in ADDRESS_TOKENS):
        return True
    return False


def _explicit_menu_context(context: dict) -> bool:
    stage = context.get("stage")
    return stage == "ordering" and bool(context.get("viewed_category") or context.get("viewed_category_group") or context.get("last_mentioned_category"))


def _is_fulfillment_context(context: dict) -> bool:
    values = [
        context.get("stage"),
        context.get("pending_question"),
        context.get("last_question_intent"),
        context.get("last_mentioned_category"),
        context.get("viewed_category"),
        context.get("viewed_category_group"),
    ]
    joined = "".join(str(value or "") for value in values)
    return any(token in joined for token in ["fulfillment", "配送", "自取", "取餐", "delivery", "pickup"])
