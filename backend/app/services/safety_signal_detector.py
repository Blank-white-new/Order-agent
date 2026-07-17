from __future__ import annotations

import re

from app.i18n.lexicon_loader import load_all_lexicons


class SafetySignalDetector:
    """Reviewed multilingual safety phrases with conservative token boundaries."""

    _PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
        (("真人", "人工", "human agent", "real person"), "EXPLICIT_HUMAN_REQUEST"),
        (("严重过敏", "致命过敏", "anaphyl", "severe allergy"), "SEVERE_ALLERGY"),
        (("交叉污染", "cross contamination", "cross-contamination"), "CROSS_CONTAMINATION"),
        (("投诉", "complaint"), "COMPLAINT"),
        (("退款", "refund"), "REFUND_REQUEST"),
        (("支付争议", "payment dispute", "chargeback"), "PAYMENT_DISPUTE"),
        (("其他顾客订单", "other customer's order", "another customer order"), "UNAUTHORIZED_ORDER_ACCESS"),
        (("其他餐厅", "other restaurant"), "CROSS_TENANT_ACCESS"),
        (("伪造商家", "fake merchant accepted", "mark merchant accepted"), "FORGE_MERCHANT_ACCEPTANCE"),
        (("绕过确认", "skip confirmation", "bypass confirmation"), "BYPASS_CONFIRMATION"),
        (("保存银行卡", "store card", "full card number"), "CARD_DATA_STORAGE"),
        (("内部提示词", "system prompt", "api key", "密钥"), "INTERNAL_SECRET_EXTRACTION"),
        (("保证不过敏", "guarantee allergen safe", "guarantee no allergen"), "UNSUPPORTED_SAFETY_GUARANTEE"),
    )

    def __init__(self) -> None:
        multilingual: list[tuple[tuple[str, ...], str]] = []
        by_signal: dict[str, list[str]] = {}
        for lexicon in load_all_lexicons().values():
            for signal, phrases in lexicon.data["safety_phrases"].items():
                by_signal.setdefault(signal, []).extend(phrases)
        for signal, phrases in sorted(by_signal.items()):
            multilingual.append((tuple(dict.fromkeys(phrase.casefold() for phrase in phrases)), signal))
        self._compiled = tuple((*self._PHRASES, *multilingual))

    def detect(self, text: str) -> frozenset[str]:
        normalized = text.casefold()
        return frozenset(
            signal
            for phrases, signal in self._compiled
            if any(self._contains(normalized, phrase.casefold()) for phrase in phrases)
        )

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        if phrase.isascii():
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))
        return phrase in text
