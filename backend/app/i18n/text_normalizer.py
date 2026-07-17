from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


MAX_TEXT_LENGTH = 1000
MAX_SEGMENTS = 256
MAX_WORD_LENGTH = 128
_ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}
_SPACE_RE = re.compile(r"\s+")
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "、": ",",
    }
)


class TextInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NormalizedText:
    original_text: str
    normalized_text: str
    comparison_text: str
    removed_control_count: int


class TextNormalizer:
    def __init__(
        self,
        *,
        max_length: int = MAX_TEXT_LENGTH,
        max_segments: int = MAX_SEGMENTS,
        max_word_length: int = MAX_WORD_LENGTH,
    ) -> None:
        self.max_length = max_length
        self.max_segments = max_segments
        self.max_word_length = max_word_length

    def normalize(self, text: str) -> NormalizedText:
        if not isinstance(text, str):
            raise TextInputError("TEXT_INVALID", "text must be a string")
        if len(text) > self.max_length:
            raise TextInputError("TEXT_TOO_LONG", "text exceeds the configured maximum length")

        nfkc = unicodedata.normalize("NFKC", text)
        cleaned: list[str] = []
        removed = 0
        for char in nfkc:
            category = unicodedata.category(char)
            if char in _ZERO_WIDTH or (category.startswith("C") and char not in {"\n", "\r", "\t"}):
                removed += 1
                continue
            cleaned.append(char)
        normalized = _SPACE_RE.sub(" ", "".join(cleaned).translate(_PUNCTUATION_TRANSLATION)).strip()
        segments = [segment for segment in re.split(r"[\s,.;:!?()\[\]]+", normalized) if segment]
        if len(segments) > self.max_segments:
            raise TextInputError("TEXT_TOO_MANY_SEGMENTS", "text contains too many segments")
        if any(len(segment) > self.max_word_length and segment.isascii() for segment in segments):
            raise TextInputError("TEXT_WORD_TOO_LONG", "text contains an excessively long word")
        if re.search(r"(.)\1{63,}", normalized, re.DOTALL):
            raise TextInputError("TEXT_EXCESSIVE_REPETITION", "text contains excessive repetition")
        return NormalizedText(
            original_text=text,
            normalized_text=normalized,
            comparison_text=normalized.casefold(),
            removed_control_count=removed,
        )
