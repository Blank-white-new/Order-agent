from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app.i18n.locales import CONCRETE_LOCALES, ZH_CN
from app.services.tenant_service import TenantService


def normalize_match_value(value: str) -> str:
    return re.sub(r"[\s,.;:!?()\[\]{}'\"，。！？；：、]+", "", value.casefold())


@dataclass(frozen=True)
class ModifierLexiconEntry:
    group_code: str
    option_code: str
    internal_name: str
    names: dict[str, str]
    aliases: dict[str, tuple[str, ...]]
    price_delta_minor: int
    active: bool

    def phrases(self, locale: str | None = None) -> tuple[str, ...]:
        locales = (locale,) if locale in CONCRETE_LOCALES else CONCRETE_LOCALES
        values: list[str] = []
        for candidate_locale in locales:
            if name := self.names.get(candidate_locale):
                values.append(name)
            values.extend(self.aliases.get(candidate_locale, ()))
        return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class MenuLexiconEntry:
    code: str
    menu_item_id: int
    menu_version_id: int
    names: dict[str, str]
    aliases: dict[str, tuple[str, ...]]
    available: bool
    modifiers: tuple[ModifierLexiconEntry, ...] = field(default_factory=tuple)

    @property
    def internal_name(self) -> str:
        return self.names.get(ZH_CN) or self.code

    def phrases(self, locale: str | None = None) -> tuple[str, ...]:
        locales = (locale,) if locale in CONCRETE_LOCALES else CONCRETE_LOCALES
        values: list[str] = []
        for candidate_locale in locales:
            if name := self.names.get(candidate_locale):
                values.append(name)
            values.extend(self.aliases.get(candidate_locale, ()))
        return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class MenuMatch:
    candidates: tuple[MenuLexiconEntry, ...]
    matched_phrases: tuple[str, ...]

    @property
    def unique(self) -> MenuLexiconEntry | None:
        return self.candidates[0] if len(self.candidates) == 1 else None


class MenuLexiconService:
    def __init__(self, uow_factory: Callable, tenant_service: TenantService) -> None:
        self.uow_factory = uow_factory
        self.tenant_service = tenant_service

    def entries(self, restaurant_code: str | None = None, branch_code: str | None = None) -> list[MenuLexiconEntry]:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            rows = uow.menus.multilingual_lexicon(tenant.branch_id)
        return [self._entry(row) for row in rows]

    @staticmethod
    def _entry(row: dict) -> MenuLexiconEntry:
        modifiers: list[ModifierLexiconEntry] = []
        for group in row.get("modifierGroups", []):
            for option in group.get("options", []):
                translations = option.get("translations", {})
                modifiers.append(
                    ModifierLexiconEntry(
                        group_code=option["groupCode"],
                        option_code=option["optionCode"],
                        internal_name=option["internalName"],
                        names={locale: data["name"] for locale, data in translations.items()},
                        aliases={
                            locale: tuple(data.get("aliases", [])) for locale, data in translations.items()
                        },
                        price_delta_minor=option["priceDeltaMinor"],
                        active=bool(option["active"]),
                    )
                )
        return MenuLexiconEntry(
            code=row["code"],
            menu_item_id=row["menuItemId"],
            menu_version_id=row["menuVersionId"],
            names=dict(row.get("names", {})),
            aliases={locale: tuple(values) for locale, values in row.get("aliases", {}).items()},
            available=bool(row.get("available", True)),
            modifiers=tuple(modifiers),
        )


class MenuMatcher:
    def match(self, text: str, entries: list[MenuLexiconEntry], *, preferred_locale: str) -> MenuMatch:
        normalized_text = normalize_match_value(text)
        code_matches = [entry for entry in entries if self._contains(text.casefold(), entry.code.casefold(), ascii_word=True)]
        if code_matches:
            return MenuMatch(tuple(code_matches), tuple(entry.code for entry in code_matches))

        preferred = self._phrase_matches(normalized_text, entries, (preferred_locale,))
        if preferred:
            return MenuMatch(tuple(item for item, _phrase in preferred), tuple(phrase for _item, phrase in preferred))
        other_locales = tuple(locale for locale in CONCRETE_LOCALES if locale != preferred_locale)
        cross_locale = self._phrase_matches(normalized_text, entries, other_locales)
        return MenuMatch(
            tuple(item for item, _phrase in cross_locale),
            tuple(phrase for _item, phrase in cross_locale),
        )

    @staticmethod
    def _phrase_matches(
        normalized_text: str,
        entries: list[MenuLexiconEntry],
        locales: tuple[str, ...],
    ) -> list[tuple[MenuLexiconEntry, str]]:
        matches: list[tuple[MenuLexiconEntry, str]] = []
        for entry in entries:
            phrases: list[str] = []
            for locale in locales:
                phrases.extend(entry.phrases(locale))
            matched = [phrase for phrase in phrases if normalize_match_value(phrase) in normalized_text]
            if matched:
                longest = max(matched, key=lambda phrase: len(normalize_match_value(phrase)))
                matches.append((entry, longest))
        return matches

    @staticmethod
    def _contains(text: str, phrase: str, *, ascii_word: bool = False) -> bool:
        if ascii_word:
            return bool(re.search(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", text))
        return phrase in text


def all_normalized_aliases(entries: list[MenuLexiconEntry]) -> set[str]:
    return {
        " ".join(phrase.casefold().split())
        for entry in entries
        for phrase in entry.phrases()
    }
