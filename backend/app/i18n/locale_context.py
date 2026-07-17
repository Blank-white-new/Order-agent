from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.i18n.locales import CONCRETE_LOCALES, MIXED


@dataclass(frozen=True)
class LocaleContext:
    requested_locale: str | None
    detected_locale: str
    dominant_locale: str
    response_locale: str
    mixed_language: bool
    confidence: float
    locale_locked: bool
    detected_scripts: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.requested_locale is not None and self.requested_locale not in CONCRETE_LOCALES:
            raise ValueError("requested_locale must be a concrete supported locale")
        if self.dominant_locale not in CONCRETE_LOCALES:
            raise ValueError("dominant_locale must be concrete")
        if self.response_locale not in CONCRETE_LOCALES:
            raise ValueError("response_locale must be concrete")
        if self.detected_locale not in (*CONCRETE_LOCALES, MIXED, "und"):
            raise ValueError("detected_locale is invalid")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.mixed_language != (self.detected_locale == MIXED):
            raise ValueError("mixed_language must agree with detected_locale")

    def serializable(self) -> dict[str, Any]:
        return asdict(self)
