#!/usr/bin/env python3
"""Standard-library validation for Phase 4 lexicons, messages and JSONL data."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
SCHEMA = ROOT / "evaluation" / "phase4_multilingual_text.schema.json"
I18N = ROOT / "backend" / "app" / "i18n"
LOCALES = ("zh-CN", "yue-Hant-HK", "en-HK")
ALL_LOCALES = (*LOCALES, "mixed")
INTENTS = {
    "MENU_QUERY", "PRICE_QUERY", "RECOMMEND", "ADD_ITEM", "REMOVE_ITEM",
    "CHANGE_QUANTITY", "REPLACE_ITEM", "ADD_MODIFIER", "REMOVE_MODIFIER",
    "ADD_NOTE", "SET_SPICY_LEVEL", "SET_FULFILLMENT_DELIVERY",
    "SET_FULFILLMENT_PICKUP", "SET_ADDRESS", "SET_PHONE", "SHOW_ORDER",
    "CONFIRM_ORDER", "CANCEL_ORDER", "START_NEW_ORDER", "SWITCH_LANGUAGE",
    "REQUEST_HUMAN", "COMPLAINT", "REFUND_REQUEST", "PAYMENT_DISPUTE", "UNKNOWN",
}
HANDOFF_REASONS = {
    "EXPLICIT_HUMAN_REQUEST", "SEVERE_ALLERGY", "CROSS_CONTAMINATION",
    "REPEATED_MISUNDERSTANDING", "AMBIGUOUS_ITEM", "AMBIGUOUS_QUANTITY",
    "UNVERIFIED_ADDRESS", "PRICE_UNAVAILABLE", "MENU_DATA_MISSING", "COMPLAINT",
    "REFUND_REQUEST", "PAYMENT_DISPUTE", "MERCHANT_REJECTED", "MERCHANT_TIMEOUT",
    "SYSTEM_FAILURE", "LANGUAGE_UNSUPPORTED", "ABUSE_OR_SECURITY", "REGULATED_ITEM",
}
REFUSAL_REASONS = {
    "CROSS_TENANT_ACCESS", "UNAUTHORIZED_ORDER_ACCESS", "FORGE_MERCHANT_ACCEPTANCE",
    "BYPASS_CONFIRMATION", "CARD_DATA_STORAGE", "UNSUPPORTED_SAFETY_GUARANTEE",
    "INTERNAL_SECRET_EXTRACTION", "SECURITY_ATTACK",
}
CLASSIFICATIONS = {"AUTO_DRAFT", "CONFIRM", "HANDOFF", "REFUSE"}
ENTITY_KEYS = {
    "item_code", "quantity", "modifier_option_code", "old_item_code",
    "fulfillment", "address_present", "phone_present",
}
REQUIRED_LEXICON_SECTIONS = {
    "intent_phrases", "quantity_words", "units", "add_words", "remove_words",
    "replace_words", "confirmation_words", "negation_words", "fulfillment_words",
    "modifier_words", "spicy_level_words", "language_switch_words", "safety_phrases",
    "address_words", "phone_words",
}
REQUIRED_MESSAGES = {
    "welcome", "menu_query", "item_not_found", "item_ambiguous", "item_unavailable",
    "quantity_clarification", "item_added", "item_removed", "order_changed",
    "fulfillment_delivery", "fulfillment_pickup", "address_confirmation",
    "phone_confirmation", "order_summary", "customer_confirmation", "safety_refuse",
    "safety_handoff", "simulated_human_warning", "handoff_failed", "language_switched",
    "language_unsupported", "merchant_not_integrated", "customer_confirmed_not_accepted",
    "clarification_required",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            fail(errors, f"{path.relative_to(ROOT)} must be UTF-8 without BOM")
        return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(errors, f"cannot parse {path.relative_to(ROOT)} as UTF-8 JSON: {exc}")
        return {}


def flatten_phrases(value):
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, str))
    elif isinstance(value, dict):
        for nested in value.values():
            yield from flatten_phrases(nested)


def validate_catalogs(errors: list[str]) -> tuple[set[str], dict]:
    menu = load_json(I18N / "catalogs" / "multilingual_menu.json", errors)
    item_codes = set(menu.get("items", {}))
    if not item_codes:
        fail(errors, "multilingual menu has no item codes")
    alias_owners: dict[tuple[str, str], str] = {}
    for code, translations in menu.get("items", {}).items():
        if set(translations) != set(LOCALES):
            fail(errors, f"menu item {code} does not have exactly three locales")
        for locale in LOCALES:
            data = translations.get(locale, {})
            if not data.get("name") or not data.get("aliases"):
                fail(errors, f"menu item {code} is missing {locale} name or alias")
            for value in (data.get("name"), *(data.get("aliases") or [])):
                normalized = " ".join(str(value).casefold().split())
                owner = alias_owners.setdefault((locale, normalized), code)
                if owner != code:
                    fail(errors, f"alias conflict in {locale}: {value!r} belongs to {owner} and {code}")
    for category, translations in menu.get("categories", {}).items():
        if set(translations) != set(LOCALES):
            fail(errors, f"category {category} does not have three translations")
    for internal, translations in menu.get("modifier_terms", {}).items():
        if set(translations) != set(LOCALES):
            fail(errors, f"modifier {internal} does not have three translations")

    for locale in LOCALES:
        lexicon = load_json(I18N / "catalogs" / f"{locale}.json", errors)
        if lexicon.get("locale") != locale:
            fail(errors, f"lexicon locale mismatch for {locale}")
        missing = REQUIRED_LEXICON_SECTIONS - set(lexicon)
        if missing:
            fail(errors, f"lexicon {locale} missing sections: {sorted(missing)}")
        owners: dict[str, str] = {}
        for section in ("intent_phrases", "language_switch_words", "safety_phrases"):
            for key, phrases in lexicon.get(section, {}).items():
                for phrase in flatten_phrases(phrases):
                    normalized = " ".join(phrase.casefold().split())
                    previous = owners.setdefault(normalized, f"{section}.{key}")
                    if previous != f"{section}.{key}":
                        fail(errors, f"dangerous conflict in {locale}: {phrase!r}: {previous}/{section}.{key}")
        messages = load_json(I18N / "messages" / f"{locale}.json", errors)
        if messages.get("locale") != locale:
            fail(errors, f"message locale mismatch for {locale}")
        keys = set(messages.get("messages", {}))
        if keys != REQUIRED_MESSAGES:
            fail(errors, f"message keys for {locale} differ: missing={sorted(REQUIRED_MESSAGES-keys)}, extra={sorted(keys-REQUIRED_MESSAGES)}")
    return item_codes, menu


def validate_dataset(errors: list[str], item_codes: set[str]) -> dict:
    load_json(SCHEMA, errors)
    rows: list[dict] = []
    seen_ids: set[str] = set()
    seen_inputs: set[tuple[str, str]] = set()
    try:
        raw = DATASET.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            fail(errors, "dataset must not contain a UTF-8 BOM")
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        fail(errors, f"cannot read dataset as UTF-8: {exc}")
        return {}
    for line_number, line in enumerate(text.splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            fail(errors, f"dataset line {line_number} is invalid JSON: {exc}")
            continue
        rows.append(row)
        sid = row.get("scenario_id")
        if sid in seen_ids:
            fail(errors, f"duplicate scenario id: {sid}")
        seen_ids.add(sid)
        signature = (row.get("locale"), " ".join(str(row.get("input", "")).split()))
        if signature in seen_inputs:
            fail(errors, f"duplicate scenario input for {signature[0]}: {signature[1]!r}")
        seen_inputs.add(signature)
        validate_row(row, line_number, item_codes, errors)
    counts = Counter(row.get("locale") for row in rows)
    for locale in ALL_LOCALES:
        if counts[locale] < 90:
            fail(errors, f"locale {locale} has {counts[locale]} scenarios; expected at least 90")
    if len(rows) < 360:
        fail(errors, f"dataset has {len(rows)} scenarios; expected at least 360")
    return {
        "total": len(rows),
        "locales": {locale: counts[locale] for locale in ALL_LOCALES},
        "intents": dict(sorted(Counter(row.get("expected_intent") for row in rows).items())),
        "ambiguous": sum("ambiguous" in row.get("tags", []) for row in rows),
        "safety": sum(row.get("expected_classification") in {"HANDOFF", "REFUSE"} for row in rows),
    }


def validate_row(row: dict, line: int, item_codes: set[str], errors: list[str]) -> None:
    prefix = f"line {line} ({row.get('scenario_id', 'unknown')})"
    required = {
        "scenario_id", "locale", "input", "expected_detected_locale", "expected_response_locale",
        "expected_intent", "expected_entities", "expected_classification", "expected_handoff_reason",
        "expected_refusal_reason", "expected_mutation", "forbidden_outcomes", "setup_inputs",
        "restaurant_code", "branch_code", "tags",
    }
    if missing := required - set(row):
        fail(errors, f"{prefix} missing fields: {sorted(missing)}")
        return
    if row["locale"] not in ALL_LOCALES:
        fail(errors, f"{prefix} invalid locale")
    if row["expected_intent"] not in INTENTS:
        fail(errors, f"{prefix} invalid intent {row['expected_intent']}")
    classification = row["expected_classification"]
    if classification not in CLASSIFICATIONS:
        fail(errors, f"{prefix} invalid classification")
    handoff, refusal = row["expected_handoff_reason"], row["expected_refusal_reason"]
    if handoff is not None and handoff not in HANDOFF_REASONS:
        fail(errors, f"{prefix} invalid handoff reason {handoff}")
    if refusal is not None and refusal not in REFUSAL_REASONS:
        fail(errors, f"{prefix} invalid refusal reason {refusal}")
    if (classification == "HANDOFF") != (handoff is not None):
        fail(errors, f"{prefix} HANDOFF classification/reason mismatch")
    if (classification == "REFUSE") != (refusal is not None):
        fail(errors, f"{prefix} REFUSE classification/reason mismatch")
    if row["expected_mutation"] and classification != "AUTO_DRAFT":
        fail(errors, f"{prefix} unsafe mutation expectation for {classification}")
    entities = row["expected_entities"]
    if not isinstance(entities, dict) or set(entities) - ENTITY_KEYS:
        fail(errors, f"{prefix} has unsupported entity fields")
    for key in ("item_code", "old_item_code"):
        if key in entities and entities[key] not in item_codes:
            fail(errors, f"{prefix} references missing menu code {entities[key]}")
    if "quantity" in entities and (not isinstance(entities["quantity"], int) or entities["quantity"] < 1):
        fail(errors, f"{prefix} quantity must be a positive integer")
    text = row["input"]
    combined = " ".join([text, *row.get("setup_inputs", [])])
    if row["locale"] == "mixed" and not (re.search(r"[\u3400-\u9fff]", text) and re.search(r"[A-Za-z]", text)):
        fail(errors, f"{prefix} mixed input lacks both Han and Latin features")
    if row["expected_intent"] == "CONFIRM_ORDER" and (
        "?" in text or "？" in text or re.search(r"\b(?:maybe|think so)\b", text.casefold())
    ):
        fail(errors, f"{prefix} question/ambiguous text is mislabeled as confirmation")
    forbidden_patterns = (
        (r"[A-Za-z]:\\Users\\", "local Windows path"),
        (r"/(?:home|Users)/[^/\s]+/", "local POSIX path"),
        (r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "email address"),
        (r"\b(?:sk-|ghp_|AKIA)[A-Za-z0-9_-]{12,}\b", "secret-like value"),
        (r"(?<!\d)1[3-9]\d{9}(?!\d)", "realistic mobile number"),
    )
    for pattern, label in forbidden_patterns:
        if re.search(pattern, combined):
            fail(errors, f"{prefix} contains {label}")


def main() -> int:
    errors: list[str] = []
    item_codes, _menu = validate_catalogs(errors)
    summary = validate_dataset(errors, item_codes)
    if errors:
        print("Phase 4 catalog validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
