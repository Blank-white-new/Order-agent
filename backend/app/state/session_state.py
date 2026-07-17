from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.schemas import dump_model


class OrderItem(BaseModel):
    item_id: str
    name: str
    price: int
    unit_price_minor: int | None = None
    currency: str = "HKD"
    menu_item_db_id: int | None = None
    menu_version_id: int | None = None
    quantity: int = 1
    options: list[str] = Field(default_factory=list)
    spicy_level: str | None = None
    exclusions: list[str] = Field(default_factory=list)
    notes: str | None = None
    category: str | None = None
    unit: str | None = None
    source: str | None = None


class DeliveryAddressCandidate(BaseModel):
    raw: str
    normalized: str
    source: str
    confidence: float
    requires_confirmation: bool = True


class SessionState(BaseModel):
    restaurant_code: str | None = None
    branch_code: str | None = None
    persistence_version: int = 0
    is_synthetic: bool = True
    draft_version: int = 1
    lifecycle_status: str = "DRAFT"
    merchant_status: str = "NOT_INTEGRATED"
    confirmation_valid: bool = False
    stage: str = "ordering"
    current_order: list[OrderItem] = Field(default_factory=list)
    last_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, list[str]] = Field(default_factory=lambda: {"avoid": [], "options": []})
    fulfillment_type: str = "delivery"
    official_delivery_address: str | None = None
    pending_delivery_address_candidate: DeliveryAddressCandidate | None = None
    pending_action: dict[str, Any] | None = None
    last_agent_action: dict[str, Any] | None = None
    last_mentioned_item: str | None = None
    last_mentioned_category: str | None = None
    viewed_category: str | None = None
    viewed_category_group: str | None = None
    pending_question: str | None = None
    last_question_intent: str | None = None
    last_mutation_snapshot: dict[str, Any] | None = None
    last_mutation_confirmed: bool = False
    last_address_mention: str | None = None
    phone: str | None = None
    submitted: bool = False
    submitted_order_id: str | None = None
    safety_classification: str = "AUTO_DRAFT"
    safety_reason_code: str | None = None
    safety_decision_id: str | None = None
    handoff_public_id: str | None = None
    handoff_status: str = "NOT_REQUIRED"
    safety_blocked_actions: list[str] = Field(default_factory=list)
    confirmed_fields: list[str] = Field(default_factory=list)
    unconfirmed_fields: list[str] = Field(default_factory=list)
    requested_locale: str | None = None
    detected_locale: str = "zh-CN"
    dominant_locale: str = "zh-CN"
    response_locale: str = "zh-CN"
    locale_locked: bool = False
    mixed_language: bool = False

    def serializable(self) -> dict[str, Any]:
        return dump_model(self)

    def clone(self) -> "SessionState":
        if hasattr(self, "model_copy"):
            return self.model_copy(deep=True)
        return self.copy(deep=True)


def order_to_dicts(items: list[OrderItem]) -> list[dict[str, Any]]:
    return [dump_model(item) for item in items]
