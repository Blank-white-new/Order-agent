from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from app.i18n.locales import CONCRETE_LOCALES, DEFAULT_LOCALE


MESSAGE_DIR = Path(__file__).with_name("messages")
LOGGER = logging.getLogger(__name__)
REQUIRED_MESSAGE_KEYS = (
    "welcome",
    "menu_query",
    "item_not_found",
    "item_ambiguous",
    "item_unavailable",
    "quantity_clarification",
    "item_added",
    "item_removed",
    "order_changed",
    "fulfillment_delivery",
    "fulfillment_pickup",
    "address_confirmation",
    "phone_confirmation",
    "order_summary",
    "customer_confirmation",
    "safety_refuse",
    "safety_handoff",
    "simulated_human_warning",
    "handoff_failed",
    "language_switched",
    "language_unsupported",
    "merchant_not_integrated",
    "customer_confirmed_not_accepted",
    "clarification_required",
)


class MessageCatalogError(RuntimeError):
    pass


@lru_cache(maxsize=len(CONCRETE_LOCALES))
def load_messages(locale: str) -> dict[str, str]:
    if locale not in CONCRETE_LOCALES:
        raise MessageCatalogError(f"unsupported response locale: {locale}")
    path = MESSAGE_DIR / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("locale") != locale or not isinstance(data.get("messages"), dict):
        raise MessageCatalogError(f"invalid message catalog: {path}")
    missing = sorted(set(REQUIRED_MESSAGE_KEYS) - set(data["messages"]))
    if missing:
        raise MessageCatalogError(f"message catalog {locale} is missing: {', '.join(missing)}")
    return dict(data["messages"])


class MessageCatalog:
    def __init__(
        self,
        *,
        environment: str = "development",
        default_locale: str = DEFAULT_LOCALE,
        audit_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.environment = environment
        self.default_locale = default_locale
        self.audit_callback = audit_callback

    def render(self, key: str, locale: str, **params: Any) -> str:
        try:
            template = load_messages(locale)[key]
            return template.format_map(_StrictFormat(params))
        except (KeyError, MessageCatalogError) as exc:
            if self.environment != "production":
                raise MessageCatalogError(f"message rendering failed for {locale}.{key}") from exc
            self._audit_fallback(locale, key)
            try:
                return load_messages(self.default_locale)[key].format_map(_StrictFormat(params))
            except (KeyError, MessageCatalogError) as fallback_exc:
                raise MessageCatalogError("safe fallback message rendering failed") from fallback_exc

    def _audit_fallback(self, locale: str, key: str) -> None:
        event = {
            "event": "MESSAGE_CATALOG_FALLBACK",
            "requestedLocale": locale,
            "messageKey": key,
        }
        if self.audit_callback:
            self.audit_callback(event)
            return
        # Contains only catalog metadata; user text and personal data are never logged.
        LOGGER.warning("message catalog fallback: %s", event)


class _StrictFormat(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise KeyError(key)
