from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


InterpretationSource = Literal["rule", "deterministic", "llm", "merged"]


def dump_model(model: Any) -> dict[str, Any]:
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class Interpretation(BaseModel):
    intent: str
    confidence: float = 0.0
    source: InterpretationSource = "deterministic"
    is_question: bool = False
    should_mutate_order: bool = False
    entities: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    target: str | None = None


class MenuItem(BaseModel):
    id: str
    name: str
    category: str
    price: int
    base_price_minor: int | None = None
    currency: str = "HKD"
    menu_item_db_id: int | None = None
    menu_version_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    spicy_level: int = 0
    available: bool = True
    options: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    recommended_score: float = 0.0
    recommend_reason: str = ""
    prep_speed: str = "normal"
    taste_profile: list[str] = Field(default_factory=list)
    portion: str = "medium"


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str
    message: str
    restaurant_id: str | None = Field(default=None, validation_alias=AliasChoices("restaurantId", "restaurant_id"))
    branch_id: str | None = Field(default=None, validation_alias=AliasChoices("branchId", "branch_id"))
    idempotency_key: str | None = Field(default=None, validation_alias=AliasChoices("idempotencyKey", "idempotency_key"))
    confidence_metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("confidenceMetadata", "confidence_metadata"),
    )
    locale: str | None = None
    locale_hint: str | None = Field(default=None, validation_alias=AliasChoices("localeHint", "locale_hint"))
    locale_locked: bool | None = Field(default=None, validation_alias=AliasChoices("localeLocked", "locale_locked"))


class ResetRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str
    restaurant_id: str | None = Field(default=None, validation_alias=AliasChoices("restaurantId", "restaurant_id"))
    branch_id: str | None = Field(default=None, validation_alias=AliasChoices("branchId", "branch_id"))
