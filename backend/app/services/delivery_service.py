from __future__ import annotations

import re


class DeliveryService:
    def normalize_address(self, address: str | None) -> str | None:
        if not address:
            return None
        cleaned = re.sub(r"[，,。？?！!\s]", "", address)
        for prefix in ["送到", "外卖到", "到"]:
            if cleaned.startswith(prefix):
                cleaned = cleaned.removeprefix(prefix)
        for suffix in ["要送多久", "送多久", "多久能送到", "要多久", "配送费多少", "多少钱", "能送吗", "能配送吗", "能送到吗"]:
            cleaned = cleaned.replace(suffix, "")
        if cleaned in {"", "这个地址", "地址", "外卖", "配送"}:
            return None
        return cleaned or None

    def estimate_eta(self, address: str) -> int:
        if "中山大学南校园" in address:
            return 32
        if "华南理工大学北门" in address:
            return 35
        return 40

    def estimate_fee(self, address: str) -> int:
        if "中山大学南校园" in address:
            return 5
        if "华南理工大学北门" in address:
            return 6
        return 8

    def can_deliver(self, address: str) -> bool:
        return bool(address)

    def extract_phone(self, text: str | None) -> str | None:
        if not text:
            return None
        match = re.search(r"1[3-9]\d{9}", text)
        return match.group(0) if match else None

    def is_valid_phone(self, phone: str | None) -> bool:
        return bool(phone and re.fullmatch(r"1[3-9]\d{9}", phone))

    def resolve_address_reference(
        self,
        text: str,
        pending: str | None,
        official: str | None,
        last: str | None,
    ) -> str | None:
        if text in {"这个地址", "这里", "这个地方", "刚才那个地址"}:
            return pending or official or last
        return self.normalize_address(text)
