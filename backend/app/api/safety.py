from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.domain.enums import HandoffFailureCode, HandoffReasonCode
from app.domain.errors import simulation_controls_disabled
from app.domain.safety import ConfidenceMetadata, SafetyEvaluationContext
from app.runtime import (
    database,
    handoff_service,
    safety_audit_service,
    store,
)


router = APIRouter()


class TenantSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: str = Field(validation_alias=AliasChoices("sessionId", "session_id"))
    restaurant_id: str | None = Field(
        default=None, validation_alias=AliasChoices("restaurantId", "restaurant_id")
    )
    branch_id: str | None = Field(default=None, validation_alias=AliasChoices("branchId", "branch_id"))


class SafetyEvaluateRequest(TenantSessionRequest):
    signals: list[str] = Field(default_factory=list, max_length=32)
    requested_action: str = Field(
        default="DRAFT_OPERATION",
        validation_alias=AliasChoices("requestedAction", "requested_action"),
        max_length=80,
    )
    required_confirmations: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("requiredConfirmations", "required_confirmations"),
        max_length=16,
    )
    confidence_metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("confidenceMetadata", "confidence_metadata"),
    )
    deterministic_input: bool = Field(
        default=False,
        validation_alias=AliasChoices("deterministicInput", "deterministic_input"),
    )


class HandoffCreateRequest(TenantSessionRequest):
    reason_code: HandoffReasonCode = Field(
        validation_alias=AliasChoices("reasonCode", "reason_code")
    )


class HandoffActionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    restaurant_id: str | None = Field(
        default=None, validation_alias=AliasChoices("restaurantId", "restaurant_id")
    )
    branch_id: str | None = Field(default=None, validation_alias=AliasChoices("branchId", "branch_id"))


class HandoffFailRequest(HandoffActionRequest):
    failure_code: HandoffFailureCode = Field(
        validation_alias=AliasChoices("failureCode", "failure_code")
    )


class HandoffResolveRequest(HandoffActionRequest):
    resolution_code: str = Field(
        default="SIMULATED_RESOLUTION",
        validation_alias=AliasChoices("resolutionCode", "resolution_code"),
        pattern=r"^[A-Z0-9_]{1,80}$",
    )
    draft_changed: bool = Field(
        default=False,
        validation_alias=AliasChoices("draftChanged", "draft_changed"),
    )


def _require_controls() -> None:
    if not database.settings.may_use_simulation_handoff_controls:
        raise simulation_controls_disabled()


@router.post("/safety/evaluate")
def evaluate_safety(request: SafetyEvaluateRequest) -> dict[str, Any]:
    state = store.get(request.session_id, request.restaurant_id, request.branch_id)
    record = safety_audit_service.evaluate_and_record(
        session_key=request.session_id,
        restaurant_code=request.restaurant_id,
        branch_code=request.branch_id,
        context=SafetyEvaluationContext(
            signals=frozenset(request.signals),
            requested_action=request.requested_action,
            required_confirmations=tuple(request.required_confirmations),
            confidence=ConfidenceMetadata.from_mapping(request.confidence_metadata),
            deterministic_input=request.deterministic_input,
        ),
    )
    return {
        "decisionId": record.public_id,
        "traceId": record.trace_id,
        "decision": record.decision.serializable(),
        "isSynthetic": state.is_synthetic,
    }


@router.post("/handoffs")
def create_handoff(request: HandoffCreateRequest) -> dict[str, Any]:
    _require_controls()
    state = store.get(request.session_id, request.restaurant_id, request.branch_id)
    record = safety_audit_service.evaluate_and_record(
        session_key=request.session_id,
        restaurant_code=request.restaurant_id,
        branch_code=request.branch_id,
        context=SafetyEvaluationContext(
            signals=frozenset({request.reason_code.value}),
            requested_action="CREATE_SIMULATED_HANDOFF",
            deterministic_input=True,
        ),
    )
    return handoff_service.request_handoff(
        session_key=request.session_id,
        state=state,
        decision=record.decision,
        trace_id=record.trace_id,
        restaurant_code=request.restaurant_id,
        branch_code=request.branch_id,
    )


@router.get("/handoffs/{public_id}")
def get_handoff(
    public_id: str,
    restaurant_id: str | None = None,
    branch_id: str | None = None,
) -> dict[str, Any]:
    return handoff_service.get(public_id, restaurant_id, branch_id)


@router.post("/handoffs/{public_id}/simulate-assign")
def simulate_assign(public_id: str, request: HandoffActionRequest) -> dict[str, Any]:
    _require_controls()
    return handoff_service.simulate_assign(public_id, request.restaurant_id, request.branch_id)


@router.post("/handoffs/{public_id}/simulate-connect")
def simulate_connect(public_id: str, request: HandoffActionRequest) -> dict[str, Any]:
    _require_controls()
    return handoff_service.simulate_connect(public_id, request.restaurant_id, request.branch_id)


@router.post("/handoffs/{public_id}/simulate-resolve")
def simulate_resolve(public_id: str, request: HandoffResolveRequest) -> dict[str, Any]:
    _require_controls()
    return handoff_service.resolve(
        public_id,
        {"resolutionCode": request.resolution_code, "draftChanged": request.draft_changed},
        request.restaurant_id,
        request.branch_id,
    )


@router.post("/handoffs/{public_id}/simulate-fail")
def simulate_fail(public_id: str, request: HandoffFailRequest) -> dict[str, Any]:
    _require_controls()
    return handoff_service.simulate_fail(
        public_id,
        request.failure_code,
        request.restaurant_id,
        request.branch_id,
    )


@router.post("/handoffs/{public_id}/cancel")
def cancel_handoff(public_id: str, request: HandoffActionRequest) -> dict[str, Any]:
    _require_controls()
    return handoff_service.cancel(public_id, request.restaurant_id, request.branch_id)
