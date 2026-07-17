from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.enums import HandoffReasonCode, RefusalReasonCode
from app.domain.safety import SafetyEvaluationContext
from app.i18n.lexicon_loader import load_all_lexicons
from app.i18n.locale_context import LocaleContext
from app.i18n.menu_lexicon import MenuLexiconEntry, MenuMatcher, ModifierLexiconEntry
from app.i18n.message_catalog import MessageCatalog, MessageCatalogError, REQUIRED_MESSAGE_KEYS, load_messages
from app.i18n.multilingual_parser import CANONICAL_INTENTS, MultilingualParser
from app.services.safety_decision_service import SafetyDecisionService


def context(locale: str = "zh-CN", *, detected: str | None = None) -> LocaleContext:
    return LocaleContext(
        requested_locale=locale,
        detected_locale=detected or locale,
        dominant_locale=locale,
        response_locale=locale,
        mixed_language=detected == "mixed",
        confidence=0.98,
        locale_locked=False,
        detected_scripts=("Han",) if locale != "en-HK" else ("Latin",),
    )


LESS_SPICY = ModifierLexiconEntry(
    group_code="spice",
    option_code="less_spicy",
    internal_name="少辣",
    names={"zh-CN": "少辣", "yue-Hant-HK": "少辣", "en-HK": "Less spicy"},
    aliases={"zh-CN": ("微辣",), "yue-Hant-HK": ("少少辣",), "en-HK": ("mild",)},
    price_delta_minor=0,
    active=True,
)
CHICKEN = MenuLexiconEntry(
    code="chicken_leg_rice",
    menu_item_id=1,
    menu_version_id=4,
    names={"zh-CN": "鸡腿饭", "yue-Hant-HK": "雞髀飯", "en-HK": "Chicken leg rice"},
    aliases={"zh-CN": ("鸡腿盖饭",), "yue-Hant-HK": ("雞髀碟頭飯",), "en-HK": ("chicken rice bowl",)},
    available=True,
    modifiers=(LESS_SPICY,),
)
BEEF = replace(
    CHICKEN,
    code="beef_rice",
    menu_item_id=2,
    names={"zh-CN": "牛肉饭", "yue-Hant-HK": "牛肉飯", "en-HK": "Beef rice"},
    aliases={"zh-CN": ("牛肉盖饭",), "yue-Hant-HK": ("牛肉碟頭飯",), "en-HK": ("beef rice bowl",)},
)


@pytest.mark.parametrize(
    ("locale", "text"),
    [
        ("zh-CN", "我要两份鸡腿盖饭，少辣"),
        ("yue-Hant-HK", "我要兩份雞髀碟頭飯，少辣"),
        ("en-HK", "I want two portions of chicken rice bowl, less spicy"),
    ],
)
def test_three_locales_map_to_same_item_quantity_modifier(locale, text):
    parsed = MultilingualParser().parse(text, context(locale), [CHICKEN, BEEF])
    assert parsed.canonical_intent == "ADD_ITEM"
    assert parsed.entities["item_code"] == "chicken_leg_rice"
    assert parsed.entities["quantity"] == 2
    assert parsed.entities["modifiers"][0]["option_code"] == "less_spicy"
    assert parsed.canonical_text == "我要2份鸡腿饭少辣"


def test_mixed_input_keeps_canonical_identity():
    parsed = MultilingualParser().parse(
        "我要 two portions Chicken leg rice 少辣 please",
        context("zh-CN", detected="mixed"),
        [CHICKEN],
    )
    assert parsed.canonical_intent == "ADD_ITEM"
    assert parsed.entities["item_code"] == CHICKEN.code
    assert parsed.entities["quantity"] == 2


def test_exact_code_has_priority_over_names():
    match = MenuMatcher().match("add 1 portion chicken_leg_rice", [CHICKEN, BEEF], preferred_locale="en-HK")
    assert match.unique == CHICKEN


def test_multiple_menu_candidates_requires_confirmation_and_no_canonical_mutation():
    parsed = MultilingualParser().parse("我要一份鸡腿饭和牛肉饭", context(), [CHICKEN, BEEF])
    assert parsed.canonical_intent == "ADD_ITEM"
    assert parsed.canonical_text is None
    assert "AMBIGUOUS_ITEM" in parsed.ambiguities
    assert set(parsed.entities["item_candidates"]) == {CHICKEN.code, BEEF.code}


def test_unknown_modifier_is_never_invented():
    parsed = MultilingualParser().parse("我要一份鸡腿饭加芝士", context(), [CHICKEN])
    assert "modifiers" not in parsed.entities


def test_unavailable_item_blocks_canonical_mutation():
    unavailable = replace(CHICKEN, available=False)
    parsed = MultilingualParser().parse("我要一份鸡腿饭", context(), [unavailable])
    assert "ITEM_UNAVAILABLE" in parsed.ambiguities
    assert parsed.canonical_text is None


def test_replace_maps_two_languages_to_authoritative_codes():
    parsed = MultilingualParser().parse("把鸡腿饭换成牛肉饭", context(), [CHICKEN, BEEF])
    assert parsed.canonical_intent == "REPLACE_ITEM"
    assert parsed.entities["old_item_code"] == CHICKEN.code
    assert parsed.entities["item_code"] == BEEF.code


def test_canonical_intent_contract_is_complete_and_language_independent():
    required = {
        "MENU_QUERY", "PRICE_QUERY", "RECOMMEND", "ADD_ITEM", "REMOVE_ITEM",
        "CHANGE_QUANTITY", "REPLACE_ITEM", "ADD_MODIFIER", "REMOVE_MODIFIER",
        "ADD_NOTE", "SET_SPICY_LEVEL", "SET_FULFILLMENT_DELIVERY",
        "SET_FULFILLMENT_PICKUP", "SET_ADDRESS", "SET_PHONE", "SHOW_ORDER",
        "CONFIRM_ORDER", "CANCEL_ORDER", "START_NEW_ORDER", "SWITCH_LANGUAGE",
        "REQUEST_HUMAN", "COMPLAINT", "REFUND_REQUEST", "PAYMENT_DISPUTE", "UNKNOWN",
    }
    assert set(CANONICAL_INTENTS) == required


def test_all_catalogs_have_identical_message_keys():
    expected = set(REQUIRED_MESSAGE_KEYS)
    for locale in ("zh-CN", "yue-Hant-HK", "en-HK"):
        assert set(load_messages(locale)) == expected


def test_missing_message_key_and_parameter_fail_closed(monkeypatch):
    catalog = MessageCatalog(environment="test")
    with pytest.raises(MessageCatalogError):
        catalog.render("not_a_key", "en-HK")
    monkeypatch.setattr(
        "app.i18n.message_catalog.load_messages",
        lambda _locale: {"item_added": "Added {item}."},
    )
    with pytest.raises(MessageCatalogError):
        catalog.render("item_added", "en-HK")


def test_production_fallback_is_audited_without_user_text(monkeypatch):
    events = []
    catalog = MessageCatalog(environment="production", audit_callback=events.append)
    real = load_messages("zh-CN")
    monkeypatch.setattr(
        "app.i18n.message_catalog.load_messages",
        lambda locale: (_ for _ in ()).throw(MessageCatalogError("missing")) if locale == "en-HK" else real,
    )
    value = catalog.render("welcome", "en-HK")
    assert value == real["welcome"]
    assert events == [{"event": "MESSAGE_CATALOG_FALLBACK", "requestedLocale": "en-HK", "messageKey": "welcome"}]


LEXICONS = load_all_lexicons()
HANDOFF_REASONS = tuple(reason.value for reason in HandoffReasonCode if reason != HandoffReasonCode.LANGUAGE_UNSUPPORTED)
REFUSAL_REASONS = tuple(reason.value for reason in RefusalReasonCode)


@pytest.mark.parametrize("locale", ("zh-CN", "yue-Hant-HK", "en-HK"))
@pytest.mark.parametrize("reason", HANDOFF_REASONS)
def test_each_handoff_reason_has_deterministic_phrase(locale, reason):
    phrases = LEXICONS[locale].data["safety_phrases"].get(reason)
    assert phrases, f"missing {locale} phrase for {reason}"
    signals = MultilingualParser().detect_safety_signals(f"context {phrases[0]} context")
    decision = SafetyDecisionService().evaluate(
        SafetyEvaluationContext(signals=frozenset(signals), deterministic_input=True)
    )
    assert decision.classification.value == "HANDOFF"
    assert decision.reason_code == reason


@pytest.mark.parametrize("locale", ("zh-CN", "yue-Hant-HK", "en-HK"))
@pytest.mark.parametrize("reason", REFUSAL_REASONS)
def test_each_refusal_reason_has_deterministic_phrase(locale, reason):
    phrases = LEXICONS[locale].data["safety_phrases"].get(reason)
    assert phrases, f"missing {locale} phrase for {reason}"
    signals = MultilingualParser().detect_safety_signals(f"context {phrases[0]} context")
    decision = SafetyDecisionService().evaluate(
        SafetyEvaluationContext(signals=frozenset(signals), deterministic_input=True)
    )
    assert decision.classification.value == "REFUSE"
    assert decision.reason_code == reason


@pytest.mark.parametrize("reason", HANDOFF_REASONS + REFUSAL_REASONS)
def test_mixed_language_safety_signal_is_not_dropped(reason):
    phrase = LEXICONS["en-HK"].data["safety_phrases"][reason][0]
    signals = MultilingualParser().detect_safety_signals(f"我要 {phrase} 唔該")
    decision = SafetyDecisionService().evaluate(
        SafetyEvaluationContext(signals=frozenset(signals), deterministic_input=True)
    )
    assert decision.reason_code == reason
