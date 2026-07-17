from __future__ import annotations

import pytest

from app.i18n.confirmation_parser import ConfirmationParser, ConfirmationResult
from app.i18n.locale_detector import LocaleDetector
from app.i18n.number_parser import NumberParser
from app.i18n.text_normalizer import TextInputError, TextNormalizer


@pytest.mark.parametrize(
    ("text", "hint", "detected", "dominant"),
    [
        ("我要两份鸡腿饭", None, "zh-CN", "zh-CN"),
        ("我要兩份雞髀飯，唔該", "yue-Hant-HK", "yue-Hant-HK", "yue-Hant-HK"),
        ("I would like two portions of chicken leg rice", None, "en-HK", "en-HK"),
        ("我要 two portions chicken leg rice", None, "mixed", "zh-CN"),
        ("add 多一份 chicken leg rice", None, "mixed", "en-HK"),
    ],
)
def test_locale_detection(text, hint, detected, dominant):
    result = LocaleDetector().detect(text, locale_hint=hint, current_response_locale="zh-CN")
    assert result.context.detected_locale == detected
    assert result.context.dominant_locale == dominant
    assert result.context.mixed_language is (detected == "mixed")


@pytest.mark.parametrize(
    ("command", "locale"),
    [
        ("请说普通话", "zh-CN"),
        ("可唔可以講廣東話", "yue-Hant-HK"),
        ("please reply in English", "en-HK"),
    ],
)
def test_explicit_language_switch_locks_response(command, locale):
    result = LocaleDetector().detect(command, current_response_locale="zh-CN")
    assert result.explicit_switch
    assert result.context.response_locale == locale
    assert result.context.locale_locked


def test_single_menu_name_does_not_switch_locked_or_current_session():
    detector = LocaleDetector()
    english = detector.detect(
        "鸡腿饭",
        current_response_locale="en-HK",
        menu_aliases={"鸡腿饭"},
    )
    chinese = detector.detect(
        "chicken leg rice",
        current_response_locale="zh-CN",
        menu_aliases={"chicken leg rice"},
    )
    assert english.context.response_locale == "en-HK"
    assert chinese.context.response_locale == "zh-CN"


@pytest.mark.parametrize("text", ["¿Habla español?", "日本語でお願いします", "говорить по-русски"])
def test_unsupported_language_is_not_defaulted_to_mandarin(text):
    result = LocaleDetector().detect(text, current_response_locale="en-HK")
    assert result.unsupported_language
    assert result.context.detected_locale == "und"
    assert result.context.response_locale == "en-HK"


def test_low_confidence_punctuation_preserves_current_response_locale():
    result = LocaleDetector().detect("...", current_response_locale="yue-Hant-HK")
    assert result.context.confidence < 0.5
    assert result.context.response_locale == "yue-Hant-HK"


def test_nfkc_punctuation_spaces_and_control_characters():
    result = TextNormalizer().normalize("  Ｉ want　２ 份，雞髀飯\u200b\x00！ ")
    assert result.original_text.endswith("！ ")
    assert result.normalized_text == "I want 2 份,雞髀飯!"
    assert result.removed_control_count == 2


def test_mixed_text_preserves_both_languages():
    result = TextNormalizer().normalize("我要 TWO 份 chicken leg rice")
    assert "我要" in result.normalized_text
    assert "TWO" in result.normalized_text
    assert result.comparison_text.endswith("chicken leg rice")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("a" * 1001, "TEXT_TOO_LONG"),
        ("a " * 257, "TEXT_TOO_MANY_SEGMENTS"),
        ("a" * 129, "TEXT_WORD_TOO_LONG"),
        ("哈" * 64, "TEXT_EXCESSIVE_REPETITION"),
    ],
)
def test_text_limits(text, code):
    with pytest.raises(TextInputError) as exc:
        TextNormalizer().normalize(text)
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("text", "value", "delta"),
    [
        ("我要一份鸡腿饭", 1, None),
        ("我要兩個雞髀飯", 2, None),
        ("two portions of chicken leg rice", 2, None),
        ("我要 three 份雞髀飯", 3, None),
        ("2x chicken leg rice", 2, None),
        ("chicken leg rice x2", 2, None),
        ("再来一份鸡腿饭", 1, 1),
        ("add another chicken leg rice", 1, 1),
        ("remove one portion", 1, -1),
    ],
)
def test_quantity_normalization(text, value, delta):
    parsed = NumberParser().parse_quantity(text, item_context=True)
    assert parsed.value == value
    assert parsed.relative_delta == delta


def test_quantity_ambiguity_and_threshold():
    ambiguous = NumberParser().parse_quantity("两份 three portions", item_context=True)
    huge = NumberParser().parse_quantity("51 portions", item_context=True)
    assert ambiguous.ambiguous and set(ambiguous.candidates) == {2, 3}
    assert huge.value is None and huge.exceeds_safe_threshold


def test_english_article_requires_item_context():
    parser = NumberParser()
    assert parser.parse_quantity("a chicken leg rice", item_context=False).value is None
    assert parser.parse_quantity("a chicken leg rice", item_context=True).value == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("确认", ConfirmationResult.EXPLICIT_CONFIRM),
        ("冇問題", ConfirmationResult.EXPLICIT_CONFIRM),
        ("yes, that's correct", ConfirmationResult.EXPLICIT_CONFIRM),
        ("不对", ConfirmationResult.EXPLICIT_REJECT),
        ("唔啱", ConfirmationResult.EXPLICIT_REJECT),
        ("no, that's wrong", ConfirmationResult.EXPLICIT_REJECT),
        ("应该吧", ConfirmationResult.AMBIGUOUS),
        ("maybe", ConfirmationResult.AMBIGUOUS),
        ("可以确认吗？", ConfirmationResult.NOT_CONFIRMATION),
        ("can you confirm?", ConfirmationResult.NOT_CONFIRMATION),
        ("鸡腿饭", ConfirmationResult.NOT_CONFIRMATION),
    ],
)
def test_strict_confirmation_semantics(text, expected):
    assert ConfirmationParser().parse(text) == expected
