from __future__ import annotations


class SafetySignalDetector:
    """A narrow deterministic safety guard, not a multilingual intent parser."""

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

    def detect(self, text: str) -> frozenset[str]:
        normalized = text.casefold()
        return frozenset(signal for phrases, signal in self._PHRASES if any(phrase in normalized for phrase in phrases))
