from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.domain.safety import ConfidenceMetadata
from app.i18n.confirmation_parser import ConfirmationParser, ConfirmationResult
from app.i18n.lexicon_loader import Lexicon, load_all_lexicons
from app.i18n.locale_context import LocaleContext
from app.i18n.menu_lexicon import MenuLexiconEntry, MenuMatcher, ModifierLexiconEntry, normalize_match_value
from app.i18n.number_parser import NumberParser


CANONICAL_INTENTS = (
    "MENU_QUERY",
    "PRICE_QUERY",
    "RECOMMEND",
    "ADD_ITEM",
    "REMOVE_ITEM",
    "CHANGE_QUANTITY",
    "REPLACE_ITEM",
    "ADD_MODIFIER",
    "REMOVE_MODIFIER",
    "ADD_NOTE",
    "SET_SPICY_LEVEL",
    "SET_FULFILLMENT_DELIVERY",
    "SET_FULFILLMENT_PICKUP",
    "SET_ADDRESS",
    "SET_PHONE",
    "SHOW_ORDER",
    "CONFIRM_ORDER",
    "CANCEL_ORDER",
    "START_NEW_ORDER",
    "SWITCH_LANGUAGE",
    "REQUEST_HUMAN",
    "COMPLAINT",
    "REFUND_REQUEST",
    "PAYMENT_DISPUTE",
    "UNKNOWN",
)

_SAFETY_TO_INTENT = {
    "EXPLICIT_HUMAN_REQUEST": "REQUEST_HUMAN",
    "COMPLAINT": "COMPLAINT",
    "REFUND_REQUEST": "REFUND_REQUEST",
    "PAYMENT_DISPUTE": "PAYMENT_DISPUTE",
}
_MUTATING_ITEM_INTENTS = {
    "ADD_ITEM",
    "REMOVE_ITEM",
    "CHANGE_QUANTITY",
    "REPLACE_ITEM",
    "ADD_MODIFIER",
    "REMOVE_MODIFIER",
    "SET_SPICY_LEVEL",
    "ADD_NOTE",
}
_QUESTION_MARKERS = ("?", "？", "吗", "嗎", "是不是", "是否", "可唔可以", "係咪", "would it")


@dataclass(frozen=True)
class ParsedUtterance:
    locale_context: LocaleContext
    canonical_intent: str
    entities: dict[str, Any]
    ambiguities: tuple[str, ...]
    required_confirmations: tuple[str, ...]
    confidence: ConfidenceMetadata
    safety_signals: tuple[str, ...]
    confirmation_result: str
    canonical_text: str | None = None

    def serializable(self, *, include_sensitive_entities: bool = False) -> dict[str, Any]:
        entities = dict(self.entities)
        if not include_sensitive_entities:
            for key in ("address", "phone", "note"):
                if key in entities:
                    entities[key] = "[redacted]"
        return {
            "localeContext": self.locale_context.serializable(),
            "canonicalIntent": self.canonical_intent,
            "entities": entities,
            "ambiguities": list(self.ambiguities),
            "requiredConfirmations": list(self.required_confirmations),
            "confidence": self.confidence.summary(),
            "safetySignals": list(self.safety_signals),
            "confirmationResult": self.confirmation_result,
            "canonicalTextAvailable": self.canonical_text is not None,
        }


class MultilingualParser:
    def __init__(self) -> None:
        self.lexicons = load_all_lexicons()
        self.number_parser = NumberParser()
        self.confirmation_parser = ConfirmationParser()
        self.menu_matcher = MenuMatcher()

    def detect_safety_signals(self, text: str) -> tuple[str, ...]:
        comparison = text.casefold()
        signals: list[str] = []
        for lexicon in self.lexicons.values():
            for signal, phrases in lexicon.data["safety_phrases"].items():
                if any(self._contains_phrase(comparison, phrase.casefold()) for phrase in phrases):
                    signals.append(signal)
        return tuple(dict.fromkeys(signals))

    def parse(
        self,
        text: str,
        locale_context: LocaleContext,
        menu_entries: list[MenuLexiconEntry],
        *,
        explicit_switch: bool = False,
        safety_signals: tuple[str, ...] = (),
    ) -> ParsedUtterance:
        comparison = text.casefold()
        confirmation = self.confirmation_parser.parse(text)
        match = self.menu_matcher.match(text, menu_entries, preferred_locale=locale_context.response_locale)
        is_question = any(marker in comparison for marker in _QUESTION_MARKERS)
        if any(phrase in comparison for phrase in ("can i get", "could i get", "i'd like", "i would like")):
            is_question = False

        if explicit_switch:
            intent = "SWITCH_LANGUAGE"
        else:
            intent = self._intent_from_safety(safety_signals) or self._detect_intent(comparison, is_question)
        if intent == "UNKNOWN" and match.candidates:
            intent = "ADD_ITEM"
        if confirmation == ConfirmationResult.EXPLICIT_CONFIRM and not is_question:
            intent = "CONFIRM_ORDER"
        elif confirmation == ConfirmationResult.EXPLICIT_REJECT and intent == "UNKNOWN":
            intent = "CANCEL_ORDER"

        entities: dict[str, Any] = {}
        ambiguities: list[str] = []
        required: list[str] = []

        if match.unique:
            item = match.unique
            entities.update(
                {
                    "item_code": item.code,
                    "item_name": item.names.get(locale_context.response_locale, item.internal_name),
                    "internal_item_name": item.internal_name,
                    "menu_version_id": item.menu_version_id,
                }
            )
            if not item.available:
                ambiguities.append("ITEM_UNAVAILABLE")
                required.append("availability")
        elif len(match.candidates) > 1:
            if intent == "REPLACE_ITEM" and len(match.candidates) == 2:
                ordered = self._order_candidates(text, match.candidates)
                entities.update(
                    {
                        "old_item_code": ordered[0].code,
                        "old_internal_item_name": ordered[0].internal_name,
                        "item_code": ordered[1].code,
                        "internal_item_name": ordered[1].internal_name,
                    }
                )
            else:
                entities["item_candidates"] = [entry.code for entry in match.candidates]
                ambiguities.append("AMBIGUOUS_ITEM")
                required.append("item")

        quantity = self.number_parser.parse_quantity(text, item_context=bool(match.candidates))
        if quantity.value is not None:
            entities["quantity"] = quantity.value
        if quantity.relative_delta is not None:
            entities["quantity_delta"] = quantity.relative_delta
        if quantity.ambiguous:
            entities["quantity_candidates"] = list(quantity.candidates)
            ambiguities.append("AMBIGUOUS_QUANTITY")
            required.append("quantity")
        if quantity.exceeds_safe_threshold:
            ambiguities.append("QUANTITY_THRESHOLD_EXCEEDED")
            required.append("quantity")
        if intent in {"ADD_ITEM", "CHANGE_QUANTITY"} and quantity.value is None and quantity.relative_delta is None:
            ambiguities.append("QUANTITY_MISSING")
            required.append("quantity")

        item_for_modifiers = match.unique
        modifier_matches = self._match_modifiers(text, item_for_modifiers, locale_context.response_locale)
        if modifier_matches:
            entities["modifiers"] = [self._modifier_entity(modifier) for modifier in modifier_matches]
        elif self._looks_like_modifier(text) and item_for_modifiers:
            ambiguities.append("MODIFIER_NOT_AVAILABLE")
            required.append("modifier")

        if intent == "SET_ADDRESS":
            entities["address"] = self._extract_after_phrase(text, self._phrases("SET_ADDRESS"))
            if not entities["address"]:
                required.append("address")
            elif "address" not in required:
                required.append("address")
        if intent == "SET_PHONE":
            phone_match = re.search(r"(?<!\d)(?:\+?\d[\d\s-]{6,17}\d)(?!\d)", text)
            entities["phone"] = re.sub(r"\D", "", phone_match.group(0)) if phone_match else None
            if not entities["phone"]:
                required.append("phone")
            elif "phone" not in required:
                required.append("phone")
        if intent == "ADD_NOTE":
            entities["note"] = self._extract_after_phrase(text, self._phrases("ADD_NOTE"))
            if not entities["note"]:
                required.append("note")

        if intent in _MUTATING_ITEM_INTENTS and not match.candidates:
            ambiguities.append("ITEM_NOT_FOUND")
            required.append("item")
        if is_question and intent in _MUTATING_ITEM_INTENTS:
            ambiguities.append("QUESTION_NOT_MUTATION")
            required.append("intent")

        canonical_text = self._canonical_text(intent, entities, modifier_matches)
        if ambiguities or is_question and intent in _MUTATING_ITEM_INTENTS:
            canonical_text = None
        confidence = self._confidence(intent, match, quantity, modifier_matches, ambiguities)
        return ParsedUtterance(
            locale_context=locale_context,
            canonical_intent=intent,
            entities=entities,
            ambiguities=tuple(dict.fromkeys(ambiguities)),
            required_confirmations=tuple(dict.fromkeys(required)),
            confidence=confidence,
            safety_signals=tuple(dict.fromkeys(safety_signals)),
            confirmation_result=confirmation.value,
            canonical_text=canonical_text,
        )

    def _detect_intent(self, comparison: str, is_question: bool) -> str:
        if "confirm" in comparison and "order" in comparison:
            return "CONFIRM_ORDER"
        if "cancel" in comparison and "order" in comparison:
            return "CANCEL_ORDER"
        if "show" in comparison and "order" in comparison:
            return "SHOW_ORDER"
        priorities = (
            "START_NEW_ORDER",
            "CANCEL_ORDER",
            "SET_FULFILLMENT_PICKUP",
            "SET_FULFILLMENT_DELIVERY",
            "REPLACE_ITEM",
            "CHANGE_QUANTITY",
            "REMOVE_ITEM",
            "SET_ADDRESS",
            "SET_PHONE",
            "SHOW_ORDER",
            "PRICE_QUERY",
            "MENU_QUERY",
            "RECOMMEND",
            "ADD_ITEM",
            "ADD_NOTE",
            "REMOVE_MODIFIER",
            "ADD_MODIFIER",
            "SET_SPICY_LEVEL",
            "CONFIRM_ORDER",
        )
        matched = [intent for intent in priorities if any(self._contains_phrase(comparison, phrase.casefold()) for phrase in self._phrases(intent))]
        if not matched:
            return "UNKNOWN"
        if is_question:
            for read_only in ("PRICE_QUERY", "MENU_QUERY", "RECOMMEND", "SHOW_ORDER"):
                if read_only in matched:
                    return read_only
        return matched[0]

    @staticmethod
    def _intent_from_safety(signals: tuple[str, ...]) -> str | None:
        return next((_SAFETY_TO_INTENT[signal] for signal in signals if signal in _SAFETY_TO_INTENT), None)

    def _phrases(self, intent: str) -> tuple[str, ...]:
        return tuple(
            phrase
            for lexicon in self.lexicons.values()
            for phrase in lexicon.data["intent_phrases"].get(intent, [])
        )

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        if phrase.isascii():
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))
        return phrase in text

    @staticmethod
    def _order_candidates(text: str, candidates: tuple[MenuLexiconEntry, ...]) -> tuple[MenuLexiconEntry, ...]:
        normalized = normalize_match_value(text)
        return tuple(
            sorted(
                candidates,
                key=lambda entry: min(
                    (normalized.find(normalize_match_value(phrase)) for phrase in entry.phrases() if normalize_match_value(phrase) in normalized),
                    default=len(normalized),
                ),
            )
        )

    @staticmethod
    def _match_modifiers(
        text: str,
        item: MenuLexiconEntry | None,
        locale: str,
    ) -> tuple[ModifierLexiconEntry, ...]:
        if not item:
            return ()
        normalized = normalize_match_value(text)
        scored: list[tuple[int, ModifierLexiconEntry]] = []
        for modifier in item.modifiers:
            if not modifier.active:
                continue
            lengths = [
                len(normalize_match_value(phrase))
                for phrase in modifier.phrases(locale) + modifier.phrases()
                if normalize_match_value(phrase) in normalized
            ]
            if lengths:
                scored.append((max(lengths), modifier))
        by_group: dict[str, list[tuple[int, ModifierLexiconEntry]]] = {}
        for score, modifier in scored:
            by_group.setdefault(modifier.group_code, []).append((score, modifier))
        selected: list[ModifierLexiconEntry] = []
        for group_matches in by_group.values():
            longest = max(score for score, _modifier in group_matches)
            selected.extend(modifier for score, modifier in group_matches if score == longest)
        unique: dict[tuple[str, str], ModifierLexiconEntry] = {}
        for modifier in selected:
            unique[(modifier.group_code, modifier.option_code)] = modifier
        return tuple(unique.values())

    def _looks_like_modifier(self, text: str) -> bool:
        normalized = text.casefold()
        return any(
            self._contains_phrase(normalized, phrase.casefold())
            for lexicon in self.lexicons.values()
            for phrase in lexicon.phrases("modifier_words")
        )

    @staticmethod
    def _modifier_entity(modifier: ModifierLexiconEntry) -> dict[str, Any]:
        return {
            "group_code": modifier.group_code,
            "option_code": modifier.option_code,
            "internal_name": modifier.internal_name,
            "price_delta_minor": modifier.price_delta_minor,
        }

    @staticmethod
    def _extract_after_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
        comparison = text.casefold()
        matches = [(comparison.find(phrase.casefold()), phrase) for phrase in phrases if phrase.casefold() in comparison]
        if not matches:
            return None
        position, phrase = min(matches, key=lambda pair: pair[0])
        value = text[position + len(phrase) :].strip(" ,.;:，。；：")
        return value or None

    @staticmethod
    def _canonical_text(
        intent: str,
        entities: dict[str, Any],
        modifiers: tuple[ModifierLexiconEntry, ...],
    ) -> str | None:
        item_name = entities.get("internal_item_name")
        quantity = entities.get("quantity")
        modifier_text = "".join(modifier.internal_name for modifier in modifiers)
        mapping = {
            "MENU_QUERY": "菜单",
            "RECOMMEND": "推荐一下",
            "SHOW_ORDER": "查看订单",
            "CONFIRM_ORDER": "确认订单",
            "CANCEL_ORDER": "取消订单",
            "START_NEW_ORDER": "开始新订单",
            "SET_FULFILLMENT_DELIVERY": "改成配送",
            "SET_FULFILLMENT_PICKUP": "改成自取",
        }
        if intent in mapping:
            return mapping[intent]
        if intent == "PRICE_QUERY" and item_name:
            return f"{item_name}多少钱"
        if intent == "ADD_ITEM" and item_name and quantity:
            return f"我要{quantity}份{item_name}{modifier_text}"
        if intent == "REMOVE_ITEM" and item_name:
            return f"{item_name}少一个" if entities.get("quantity_delta") == -1 else f"删除{item_name}"
        if intent == "CHANGE_QUANTITY" and item_name and quantity:
            if entities.get("quantity_delta") == -1:
                return f"{item_name}少一个"
            quantity_text = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五"}.get(quantity, str(quantity))
            return f"{item_name}改成{quantity_text}份"
        if intent == "REPLACE_ITEM" and item_name and entities.get("old_internal_item_name"):
            return f"把{entities['old_internal_item_name']}换成{item_name}"
        if intent in {"ADD_MODIFIER", "REMOVE_MODIFIER", "SET_SPICY_LEVEL"} and item_name and modifier_text:
            return f"给{item_name}{modifier_text}"
        if intent == "SET_ADDRESS" and entities.get("address"):
            return f"地址是{entities['address']}"
        if intent == "SET_PHONE" and entities.get("phone"):
            return f"电话是{entities['phone']}"
        if intent == "ADD_NOTE" and item_name and entities.get("note"):
            return f"给{item_name}备注{entities['note']}"
        return None

    @staticmethod
    def _confidence(intent, match, quantity, modifiers, ambiguities) -> ConfidenceMetadata:
        intent_confidence = 0.99 if intent != "UNKNOWN" else 0.35
        item_confidence = 0.99 if match.unique else (0.4 if match.candidates else None)
        quantity_confidence = 0.99 if quantity.value is not None else (0.4 if quantity.candidates else None)
        modifier_confidence = 0.99 if modifiers else None
        present = [value for value in (intent_confidence, item_confidence, quantity_confidence, modifier_confidence) if value is not None]
        overall = min(present) if present else 0.35
        if ambiguities:
            overall = min(overall, 0.55)
        return ConfidenceMetadata(
            intent_confidence=intent_confidence,
            item_confidence=item_confidence,
            quantity_confidence=quantity_confidence,
            modifier_confidence=modifier_confidence,
            overall_confidence=overall,
        )
