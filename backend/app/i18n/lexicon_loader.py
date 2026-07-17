from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.i18n.locales import CONCRETE_LOCALES


CATALOG_DIR = Path(__file__).with_name("catalogs")
REQUIRED_SECTIONS = (
    "intent_phrases",
    "quantity_words",
    "units",
    "add_words",
    "remove_words",
    "replace_words",
    "confirmation_words",
    "negation_words",
    "fulfillment_words",
    "modifier_words",
    "spicy_level_words",
    "language_switch_words",
    "safety_phrases",
    "address_words",
    "phone_words",
)


@dataclass(frozen=True)
class Lexicon:
    locale: str
    data: dict[str, Any]

    def phrases(self, section: str, key: str | None = None) -> tuple[str, ...]:
        value = self.data[section]
        if key is not None:
            value = value.get(key, [])
        if isinstance(value, dict):
            return tuple(phrase for phrases in value.values() for phrase in phrases)
        return tuple(value)


@lru_cache(maxsize=len(CONCRETE_LOCALES))
def load_lexicon(locale: str) -> Lexicon:
    if locale not in CONCRETE_LOCALES:
        raise ValueError(f"unsupported lexicon locale: {locale}")
    path = CATALOG_DIR / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("locale") != locale:
        raise ValueError(f"lexicon locale mismatch: {path}")
    missing = [section for section in REQUIRED_SECTIONS if section not in data]
    if missing:
        raise ValueError(f"lexicon is missing sections: {', '.join(missing)}")
    _validate_conflicts(data)
    return Lexicon(locale=locale, data=data)


def load_all_lexicons() -> dict[str, Lexicon]:
    return {locale: load_lexicon(locale) for locale in CONCRETE_LOCALES}


def _validate_conflicts(data: dict[str, Any]) -> None:
    ownership: dict[str, str] = {}
    dangerous_sections = ("intent_phrases", "language_switch_words", "safety_phrases")
    for section in dangerous_sections:
        for key, phrases in data[section].items():
            for phrase in phrases:
                normalized = " ".join(phrase.casefold().split())
                owner = ownership.get(normalized)
                if owner and owner != f"{section}.{key}":
                    raise ValueError(f"dangerous lexicon conflict for {phrase!r}: {owner} vs {section}.{key}")
                ownership[normalized] = f"{section}.{key}"
