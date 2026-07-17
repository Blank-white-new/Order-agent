from __future__ import annotations

import re
from enum import StrEnum

from app.i18n.lexicon_loader import load_all_lexicons


class ConfirmationResult(StrEnum):
    EXPLICIT_CONFIRM = "EXPLICIT_CONFIRM"
    EXPLICIT_REJECT = "EXPLICIT_REJECT"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_CONFIRMATION = "NOT_CONFIRMATION"


_AMBIGUOUS = ("差不多", "应该吧", "應該啦", "maybe", "i think so", "大概", "可能")
_QUESTION_PREFIXES = ("是不是", "是否", "可唔可以", "係咪", "can ", "could ", "would ", "do ", "is ", "are ")


class ConfirmationParser:
    def __init__(self) -> None:
        self.lexicons = load_all_lexicons()

    def parse(self, text: str) -> ConfirmationResult:
        compact = " ".join(text.casefold().strip().split())
        if not compact:
            return ConfirmationResult.NOT_CONFIRMATION
        if "?" in compact or "？" in compact or compact.startswith(_QUESTION_PREFIXES):
            return ConfirmationResult.NOT_CONFIRMATION
        if any(phrase in compact for phrase in _AMBIGUOUS):
            return ConfirmationResult.AMBIGUOUS
        negations = {
            phrase.casefold()
            for lexicon in self.lexicons.values()
            for phrase in lexicon.phrases("negation_words")
        }
        confirmations = {
            phrase.casefold()
            for lexicon in self.lexicons.values()
            for phrase in lexicon.phrases("confirmation_words", "confirm")
        }
        rejections = {
            phrase.casefold()
            for lexicon in self.lexicons.values()
            for phrase in lexicon.phrases("confirmation_words", "reject")
        }
        if compact in rejections or any(re.fullmatch(rf"{re.escape(value)}[.!。！]?", compact) for value in rejections):
            return ConfirmationResult.EXPLICIT_REJECT
        if any(_contains_phrase(compact, value) for value in rejections):
            return ConfirmationResult.EXPLICIT_REJECT
        if any(negation in compact for negation in negations) and compact not in {"没问题", "冇問題", "no problem"}:
            return ConfirmationResult.EXPLICIT_REJECT if compact in rejections else ConfirmationResult.NOT_CONFIRMATION
        if compact.rstrip(".!。！") in confirmations:
            return ConfirmationResult.EXPLICIT_CONFIRM
        if (
            any(len(value) >= 2 and _contains_phrase(compact, value) for value in confirmations)
            and len(compact) <= 64
            and not any(negation in compact for negation in negations)
        ):
            return ConfirmationResult.EXPLICIT_CONFIRM
        return ConfirmationResult.NOT_CONFIRMATION


def _contains_phrase(text: str, phrase: str) -> bool:
    if phrase.isascii():
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))
    return phrase in text
