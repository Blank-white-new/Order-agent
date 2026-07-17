from __future__ import annotations

import re
from dataclasses import dataclass

from app.i18n.lexicon_loader import load_all_lexicons
from app.i18n.locale_context import LocaleContext
from app.i18n.locales import DEFAULT_LOCALE, EN_HK, MIXED, YUE_HANT_HK, ZH_CN, concrete_response_locale


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")
_UNSUPPORTED_SCRIPT_RE = re.compile(
    r"[\u0400-\u04ff\u0600-\u06ff\u0900-\u097f\u3040-\u30ff\uac00-\ud7af]"
)
_YUE_MARKERS = (
    "唔",
    "冇",
    "係",
    "嘅",
    "喺",
    "咁",
    "俾",
    "佢",
    "搵",
    "啱",
    "廣東話",
    "講",
    "轉做",
    "外賣",
    "加底",
    "走辣",
    "走冰",
    "呢個",
    "幾多",
    "有咩",
    "咩",
    "而家",
    "唔該",
    "幫我",
    "張單",
    "落單",
    "住先",
    "人哋",
    "咗",
    "嚟",
    "拎",
    "係咪",
    "雞髀",
    "改做",
    "呢",
    "攞",
    "畀",
    "喇",
)
_ZH_MARKERS = ("普通话", "普通話", "请", "这", "个", "没", "说", "确认", "订单", "配送", "我要", "再加", "份")
_STRONG_ZH_MARKERS = ("普通话", "请", "这", "个", "没", "说", "确认", "订单", "配送")
_UNSUPPORTED_LANGUAGE_NAMES = (
    "法语",
    "法語",
    "德语",
    "德語",
    "日语",
    "日語",
    "韩语",
    "韓語",
    "french",
    "german",
    "japanese",
    "日本語",
    "korean",
)
_EN_SENTENCE_MARKERS = {
    "i",
    "i'd",
    "please",
    "can",
    "could",
    "would",
    "want",
    "like",
    "add",
    "remove",
    "make",
    "switch",
    "continue",
    "delivery",
    "pickup",
    "confirm",
}


@dataclass(frozen=True)
class LocaleDetection:
    context: LocaleContext
    explicit_switch: bool
    unsupported_language: bool


class LocaleDetector:
    def __init__(self) -> None:
        self.lexicons = load_all_lexicons()

    def detect(
        self,
        text: str,
        *,
        requested_locale: str | None = None,
        locale_hint: str | None = None,
        locale_locked: bool | None = None,
        current_response_locale: str | None = None,
        current_locale_locked: bool = False,
        menu_aliases: set[str] | None = None,
    ) -> LocaleDetection:
        explicit_locale = self._explicit_language_switch(text)
        current = concrete_response_locale(current_response_locale, DEFAULT_LOCALE)
        lock = current_locale_locked if locale_locked is None else locale_locked
        requested = explicit_locale or requested_locale or (locale_hint if locale_locked else None)
        if explicit_locale:
            lock = True

        scripts = self._scripts(text)
        unsupported = (
            bool(_UNSUPPORTED_SCRIPT_RE.search(text))
            or any(marker in text for marker in ("¿", "¡"))
            or any(name in text.casefold() for name in _UNSUPPORTED_LANGUAGE_NAMES)
        )
        if unsupported:
            return LocaleDetection(
                context=LocaleContext(
                    requested_locale=requested,
                    detected_locale="und",
                    dominant_locale=current,
                    response_locale=explicit_locale or concrete_response_locale(requested, current),
                    mixed_language=False,
                    confidence=0.2,
                    locale_locked=lock,
                    detected_scripts=scripts,
                ),
                explicit_switch=bool(explicit_locale),
                unsupported_language=True,
            )

        has_cjk = bool(_CJK_RE.search(text))
        english_words = [word.casefold() for word in _LATIN_WORD_RE.findall(text)]
        has_latin = bool(english_words)
        yue_score = sum(text.count(marker) for marker in _YUE_MARKERS)
        zh_score = sum(text.count(marker) for marker in _ZH_MARKERS)
        strong_zh_score = sum(text.count(marker) for marker in _STRONG_ZH_MARKERS)
        en_score = sum(word in _EN_SENTENCE_MARKERS for word in english_words)
        if english_words and english_words[0] in _EN_SENTENCE_MARKERS and len(english_words) >= 3:
            en_score += 1

        if has_cjk and has_latin:
            detected = MIXED
            if yue_score > zh_score and yue_score >= en_score:
                dominant = YUE_HANT_HK
            elif en_score > max(yue_score, zh_score):
                dominant = EN_HK
            elif zh_score > yue_score:
                dominant = ZH_CN
            else:
                dominant = current
            confidence = 0.98
        elif has_cjk:
            detected = YUE_HANT_HK if yue_score > 0 or (locale_hint == YUE_HANT_HK and strong_zh_score == 0) else ZH_CN
            dominant = detected
            confidence = 0.96 if yue_score > 0 or zh_score > 0 else (0.92 if locale_hint else 0.82)
        elif has_latin:
            detected = EN_HK
            dominant = EN_HK
            confidence = 0.97 if en_score > 0 or len(english_words) >= 3 else 0.78
        else:
            detected = current
            dominant = current
            confidence = 0.35

        normalized_alias = " ".join(text.casefold().split())
        single_menu_name = bool(menu_aliases and normalized_alias in menu_aliases)
        if explicit_locale:
            response = explicit_locale
        elif requested:
            response = requested
        elif lock:
            response = current
        elif single_menu_name and dominant != current:
            response = current
        elif detected == MIXED:
            response = dominant
        elif confidence >= 0.9:
            response = dominant
        else:
            response = current

        return LocaleDetection(
            context=LocaleContext(
                requested_locale=requested,
                detected_locale=detected,
                dominant_locale=dominant,
                response_locale=response,
                mixed_language=detected == MIXED,
                confidence=confidence,
                locale_locked=lock,
                detected_scripts=scripts,
            ),
            explicit_switch=bool(explicit_locale),
            unsupported_language=False,
        )

    def _explicit_language_switch(self, text: str) -> str | None:
        comparison = text.casefold()
        for locale, lexicon in self.lexicons.items():
            if any(phrase.casefold() in comparison for phrase in lexicon.phrases("language_switch_words", locale)):
                return locale
        return None

    @staticmethod
    def _scripts(text: str) -> tuple[str, ...]:
        scripts: list[str] = []
        if _CJK_RE.search(text):
            scripts.append("Han")
        if _LATIN_WORD_RE.search(text):
            scripts.append("Latin")
        if _UNSUPPORTED_SCRIPT_RE.search(text):
            scripts.append("Other")
        if any(char.isdigit() for char in text):
            scripts.append("Digit")
        return tuple(scripts)
