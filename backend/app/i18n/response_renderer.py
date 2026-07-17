from __future__ import annotations

from app.i18n.message_catalog import MessageCatalog
from app.i18n.multilingual_parser import ParsedUtterance
from app.i18n.menu_lexicon import MenuLexiconEntry


class ResponseRenderer:
    def __init__(self, catalog: MessageCatalog) -> None:
        self.catalog = catalog

    def render_switch(self, locale: str) -> str:
        return self.catalog.render("language_switched", locale)

    def render_safety(self, locale: str, classification: str, reason_code: str | None) -> str:
        if reason_code == "LANGUAGE_UNSUPPORTED":
            return self.catalog.render("language_unsupported", locale)
        if classification == "REFUSE":
            return self.catalog.render("safety_refuse", locale, reason=reason_code or "SAFETY_POLICY")
        if classification == "HANDOFF":
            return self.catalog.render("safety_handoff", locale, reason=reason_code or "SAFETY_POLICY")
        return self.catalog.render("clarification_required", locale)

    def render_item_candidates(
        self,
        parsed: ParsedUtterance,
        entries: tuple[MenuLexiconEntry, ...],
    ) -> str:
        locale = parsed.locale_context.response_locale
        requested = set(parsed.entities.get("item_candidates", []))
        names = [
            entry.names.get(locale, entry.internal_name)
            for entry in entries
            if entry.code in requested
        ]
        base = self.catalog.render("item_ambiguous", locale)
        return f"{base} {' / '.join(names)}" if names else base

    def render_result(self, parsed: ParsedUtterance, result: dict) -> str:
        locale = parsed.locale_context.response_locale
        intent = parsed.canonical_intent
        entities = parsed.entities
        trace = result.get("trace", {})
        mutating = intent in {
            "ADD_ITEM",
            "REMOVE_ITEM",
            "CHANGE_QUANTITY",
            "REPLACE_ITEM",
            "ADD_MODIFIER",
            "REMOVE_MODIFIER",
            "SET_SPICY_LEVEL",
            "SET_FULFILLMENT_DELIVERY",
            "SET_FULFILLMENT_PICKUP",
            "SET_ADDRESS",
            "SET_PHONE",
            "ADD_NOTE",
        }
        if mutating and (
            trace.get("stateMutationAllowed") is False
            or trace.get("orderBefore") == trace.get("orderAfter")
            and intent in {"ADD_ITEM", "REMOVE_ITEM", "CHANGE_QUANTITY", "REPLACE_ITEM"}
        ):
            return self.catalog.render("clarification_required", locale)
        if parsed.ambiguities:
            if "AMBIGUOUS_ITEM" in parsed.ambiguities:
                return self.catalog.render("item_ambiguous", locale)
            if "ITEM_NOT_FOUND" in parsed.ambiguities:
                return self.catalog.render("item_not_found", locale)
            if "ITEM_UNAVAILABLE" in parsed.ambiguities:
                return self.catalog.render("item_unavailable", locale)
            if any(value.startswith("QUANTITY_") or value == "AMBIGUOUS_QUANTITY" for value in parsed.ambiguities):
                return self.catalog.render("quantity_clarification", locale)
            return self.catalog.render("clarification_required", locale)

        item_name = entities.get("item_name") or entities.get("item_code") or ""
        handlers = {
            "ADD_ITEM": ("item_added", {"item": item_name, "quantity": entities.get("quantity", 1)}),
            "REMOVE_ITEM": ("item_removed", {"item": item_name}),
            "CHANGE_QUANTITY": ("order_changed", {"item": item_name}),
            "REPLACE_ITEM": ("order_changed", {"item": item_name}),
            "ADD_MODIFIER": ("order_changed", {"item": item_name}),
            "REMOVE_MODIFIER": ("order_changed", {"item": item_name}),
            "SET_SPICY_LEVEL": ("order_changed", {"item": item_name}),
            "SET_FULFILLMENT_DELIVERY": ("fulfillment_delivery", {}),
            "SET_FULFILLMENT_PICKUP": ("fulfillment_pickup", {}),
            "SET_ADDRESS": ("address_confirmation", {}),
            "SET_PHONE": ("phone_confirmation", {}),
            "SHOW_ORDER": ("order_summary", {}),
            "MENU_QUERY": ("menu_query", {}),
            "PRICE_QUERY": ("menu_query", {}),
            "RECOMMEND": ("menu_query", {}),
            "CONFIRM_ORDER": ("customer_confirmed_not_accepted", {}),
        }
        key, params = handlers.get(intent, ("clarification_required", {}))
        return self.catalog.render(key, locale, **params)
