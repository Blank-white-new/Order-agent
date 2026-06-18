from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


ALLOWED_LLM_INTENTS = {
    "add_item",
    "remove_item",
    "update_quantity",
    "ask_menu",
    "ask_recommendation",
    "delivery",
    "pickup",
    "confirm_order",
    "cancel_order",
    "clarify",
    "smalltalk",
    "unknown",
}

ALLOWED_LLM_ACTION_TYPES = {
    "add_item",
    "remove_item",
    "update_quantity",
    "set_delivery",
    "set_pickup",
    "ask_menu",
    "ask_recommendation",
    "confirm_order",
    "cancel_order",
}


class LLMFallbackAction(BaseModel):
    type: str
    item_name: str | None = None
    quantity: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    target: str | None = None


class LLMFallbackInterpretation(BaseModel):
    intent: str
    confidence: float
    normalized_text: str | None = None
    actions: list[LLMFallbackAction] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    user_facing_reply: str | None = None
