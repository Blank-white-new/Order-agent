from __future__ import annotations

import re


_ORDINAL_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
}
_SAFE_PREFIX_RE = r"(?:帮我选|帮我来|给我来|给我选|就|选|要|来)?"
_SAFE_SUFFIX_RE = r"(?:来一份|加一份)?"
_PARTICLE_RE = r"[吧呀啊呢哦哈嘛]*"
_ORDINAL_RE = re.compile(
    rf"^{_SAFE_PREFIX_RE}第(?P<number>[一二三四五六七八九1-9])个{_PARTICLE_RE}{_SAFE_SUFFIX_RE}{_PARTICLE_RE}$"
)


def normalize_recommendation_ordinal_reference(text: str | None) -> int | None:
    compact = _compact(text)
    if not compact:
        return None
    match = _ORDINAL_RE.fullmatch(compact)
    if not match:
        return None
    number = _ORDINAL_NUMBERS.get(match.group("number"))
    if number is None:
        return None
    return number - 1


def _compact(text: str | None) -> str:
    return re.sub(r"[\s，,。！？!?；;、：:\"'“”‘’（）()【】\[\].…-]+", "", text or "")
