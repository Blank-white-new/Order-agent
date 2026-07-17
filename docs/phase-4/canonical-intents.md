# Canonical intents

All three languages and mixed input map to the same business vocabulary:

```text
MENU_QUERY PRICE_QUERY RECOMMEND ADD_ITEM REMOVE_ITEM CHANGE_QUANTITY
REPLACE_ITEM ADD_MODIFIER REMOVE_MODIFIER ADD_NOTE SET_SPICY_LEVEL
SET_FULFILLMENT_DELIVERY SET_FULFILLMENT_PICKUP SET_ADDRESS SET_PHONE
SHOW_ORDER CONFIRM_ORDER CANCEL_ORDER START_NEW_ORDER SWITCH_LANGUAGE
REQUEST_HUMAN COMPLAINT REFUND_REQUEST PAYMENT_DISPUTE UNKNOWN
```

`ParsedUtterance` carries the `LocaleContext`, canonical intent, normalized entities, ambiguities, required confirmations, field-level/overall confidence, safety signals, strict confirmation result, and an optional internal canonical command. The internal command is consumed by the existing Orchestrator; it is not a second business implementation.

Menu entities use `menu_item.code` and modifier entities use authoritative group/option codes. Matching order is exact item code, preferred-locale name, preferred-locale alias, other supported names for code-switched text, and a unique normalized candidate. Multiple candidates or quantities block the canonical mutation. There is no edit-distance auto-ordering.

Confirmation parsing returns `EXPLICIT_CONFIRM`, `EXPLICIT_REJECT`, `AMBIGUOUS`, or `NOT_CONFIRMATION`. Questions, negation, “maybe”, “I think so”, conditional language and isolated item names are not final confirmation. Explicit confirmation still passes the Phase 2 confirmation-version lifecycle and Phase 3 safety rules.
