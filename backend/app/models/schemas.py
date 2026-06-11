from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    session_id: str
    message: str


class ResetRequest(BaseModel):
    session_id: str
