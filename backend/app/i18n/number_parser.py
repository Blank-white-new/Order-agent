from __future__ import annotations

import re
from dataclasses import dataclass


MAX_QUANTITY = 50
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_ENGLISH_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_UNITS = r"(?:份|個|个|杯|碗|portion(?:s)?|cup(?:s)?|bowl(?:s)?)"


@dataclass(frozen=True)
class QuantityParse:
    value: int | None
    candidates: tuple[int, ...]
    ambiguous: bool
    relative_delta: int | None = None
    exceeds_safe_threshold: bool = False


class NumberParser:
    def __init__(self, *, max_quantity: int = MAX_QUANTITY) -> None:
        self.max_quantity = max_quantity

    def parse_quantity(self, text: str, *, item_context: bool = False) -> QuantityParse:
        normalized = text.casefold()
        relative_delta = self._relative_delta(normalized)
        candidates: list[int] = []

        for pattern in (rf"(?<!\w)(\d{{1,3}})\s*[x×](?!\w)", rf"(?<!\w)[x×]\s*(\d{{1,3}})(?!\w)"):
            candidates.extend(int(value) for value in re.findall(pattern, normalized))
        candidates.extend(int(value) for value in re.findall(rf"(?<!\w)(\d{{1,3}})\s*{_UNITS}", normalized))

        for token, value in _ENGLISH_NUMBERS.items():
            if re.search(rf"\b{token}\s*{_UNITS}(?![a-z])", normalized):
                candidates.append(value)
            if re.search(rf"\b(?:make it|change to)\s+{token}\b", normalized):
                candidates.append(value)
        for token, value in _CHINESE_DIGITS.items():
            if re.search(rf"{re.escape(token)}\s*{_UNITS}", normalized):
                candidates.append(value)

        if item_context and re.search(r"\b(?:a|an)\s+(?=[a-z])", normalized):
            candidates.append(1)
        if re.search(r"(?:一份|一個|一个|one more|add another|再来一份|再來一份|加一个|加一個|加多一份|要多個)", normalized):
            candidates.append(1)

        unique = tuple(dict.fromkeys(candidates))
        ambiguous = len(unique) > 1
        value = unique[0] if len(unique) == 1 else None
        exceeds = any(candidate > self.max_quantity for candidate in unique)
        if value is not None and (value <= 0 or exceeds):
            value = None
        return QuantityParse(
            value=value,
            candidates=unique,
            ambiguous=ambiguous,
            relative_delta=relative_delta,
            exceeds_safe_threshold=exceeds,
        )

    @staticmethod
    def _relative_delta(text: str) -> int | None:
        if re.search(r"(?:one more|add another|再来一份|再來一份|加一个|加一個|加多一份|要多個)", text):
            return 1
        if re.search(r"(?:remove one|少一个|少一個)", text):
            return -1
        return None
