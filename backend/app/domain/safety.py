from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from app.domain.enums import DecisionClass


CONFIDENCE_FIELDS = (
    "intent_confidence",
    "item_confidence",
    "quantity_confidence",
    "modifier_confidence",
    "address_confidence",
    "phone_confidence",
    "overall_confidence",
)


@dataclass(frozen=True)
class ConfidenceMetadata:
    intent_confidence: float | None = None
    item_confidence: float | None = None
    quantity_confidence: float | None = None
    modifier_confidence: float | None = None
    address_confidence: float | None = None
    phone_confidence: float | None = None
    overall_confidence: float | None = None
    contradictory_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in CONFIDENCE_FIELDS:
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        invalid = set(self.contradictory_fields) - set(CONFIDENCE_FIELDS)
        if invalid:
            raise ValueError("contradictory_fields contains an unsupported confidence field")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ConfidenceMetadata":
        if not value:
            return cls()
        normalized = {key: value.get(key) for key in CONFIDENCE_FIELDS}
        normalized["contradictory_fields"] = tuple(value.get("contradictory_fields") or ())
        return cls(**normalized)

    @property
    def present_values(self) -> tuple[float, ...]:
        return tuple(value for name in CONFIDENCE_FIELDS if (value := getattr(self, name)) is not None)

    @property
    def effective_overall(self) -> float | None:
        if self.overall_confidence is not None:
            return self.overall_confidence
        values = self.present_values
        return min(values) if values else None

    def summary(self) -> dict[str, Any]:
        return {
            **{name: getattr(self, name) for name in CONFIDENCE_FIELDS},
            "contradictory_fields": list(self.contradictory_fields),
            "missing": [name for name in CONFIDENCE_FIELDS if getattr(self, name) is None],
        }


@dataclass(frozen=True)
class SafetyCounters:
    consecutive_low_confidence: int = 0
    consecutive_misunderstandings: int = 0
    consecutive_corrections: int = 0
    confirmation_failures: int = 0


@dataclass(frozen=True)
class SafetyEvaluationContext:
    signals: frozenset[str] = field(default_factory=frozenset)
    requested_action: str = "DRAFT_OPERATION"
    required_confirmations: tuple[str, ...] = ()
    confidence: ConfidenceMetadata = field(default_factory=ConfidenceMetadata)
    counters: SafetyCounters = field(default_factory=SafetyCounters)
    deterministic_input: bool = False
    risk_ids: tuple[str, ...] = ()
    metric_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SafetyDecision:
    classification: DecisionClass
    reason_code: str | None
    confidence: float | None
    required_confirmations: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    risk_ids: tuple[str, ...]
    metric_ids: tuple[str, ...]
    explanation_code: str

    def __post_init__(self) -> None:
        if self.classification in {DecisionClass.HANDOFF, DecisionClass.REFUSE} and not self.reason_code:
            raise ValueError(f"{self.classification.value} decisions require a reason_code")
        if self.classification == DecisionClass.CONFIRM and not self.required_confirmations:
            raise ValueError("CONFIRM decisions require at least one confirmation field")

    def serializable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["classification"] = self.classification.value
        return payload
