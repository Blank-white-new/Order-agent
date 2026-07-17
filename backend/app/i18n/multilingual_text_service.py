from __future__ import annotations

from dataclasses import dataclass

from app.i18n.locale_detector import LocaleDetector
from app.i18n.locales import CONCRETE_LOCALES, validate_requested_locale
from app.i18n.menu_lexicon import MenuLexiconEntry, MenuLexiconService, all_normalized_aliases
from app.i18n.multilingual_parser import MultilingualParser, ParsedUtterance
from app.i18n.response_renderer import ResponseRenderer
from app.i18n.text_normalizer import NormalizedText, TextNormalizer


@dataclass(frozen=True)
class MultilingualTextAnalysis:
    normalized: NormalizedText
    parsed: ParsedUtterance
    menu_entries: tuple[MenuLexiconEntry, ...]
    explicit_switch: bool
    unsupported_language: bool

    @property
    def safety_signals(self) -> tuple[str, ...]:
        signals = list(self.parsed.safety_signals)
        if self.unsupported_language:
            signals.append("LANGUAGE_UNSUPPORTED")
        if "AMBIGUOUS_ITEM" in self.parsed.ambiguities:
            signals.append("AMBIGUOUS_ITEM_CANDIDATES")
        if "AMBIGUOUS_QUANTITY" in self.parsed.ambiguities:
            signals.append("AMBIGUOUS_QUANTITY_CANDIDATES")
        return tuple(dict.fromkeys(signals))


class MultilingualTextService:
    def __init__(
        self,
        menu_lexicon_service: MenuLexiconService,
        response_renderer: ResponseRenderer,
    ) -> None:
        self.menu_lexicon_service = menu_lexicon_service
        self.response_renderer = response_renderer
        self.normalizer = TextNormalizer()
        self.locale_detector = LocaleDetector()
        self.parser = MultilingualParser()

    def analyze(
        self,
        text: str,
        state,
        *,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        locale: str | None = None,
        locale_hint: str | None = None,
        locale_locked: bool | None = None,
    ) -> MultilingualTextAnalysis:
        validate_requested_locale(locale)
        validate_requested_locale(locale_hint)
        normalized = self.normalizer.normalize(text)
        entries = self.menu_lexicon_service.entries(restaurant_code, branch_code)
        detection = self.locale_detector.detect(
            normalized.normalized_text,
            requested_locale=locale,
            locale_hint=locale_hint,
            locale_locked=locale_locked,
            current_response_locale=getattr(state, "response_locale", None),
            current_locale_locked=bool(getattr(state, "locale_locked", False)),
            menu_aliases=all_normalized_aliases(entries),
        )
        safety_signals = self.parser.detect_safety_signals(normalized.normalized_text)
        parsed = self.parser.parse(
            normalized.normalized_text,
            detection.context,
            entries,
            explicit_switch=detection.explicit_switch,
            safety_signals=safety_signals,
            pending_action=getattr(state, "pending_action", None),
            has_recommendations=bool(getattr(state, "last_recommendations", [])),
        )
        return MultilingualTextAnalysis(
            normalized=normalized,
            parsed=parsed,
            menu_entries=tuple(entries),
            explicit_switch=detection.explicit_switch,
            unsupported_language=detection.unsupported_language,
        )

    @staticmethod
    def apply_locale_state(state, analysis: MultilingualTextAnalysis) -> None:
        context = analysis.parsed.locale_context
        state.requested_locale = context.requested_locale
        state.detected_locale = context.detected_locale
        state.dominant_locale = context.dominant_locale
        state.response_locale = context.response_locale
        state.locale_locked = context.locale_locked
        state.mixed_language = context.mixed_language
