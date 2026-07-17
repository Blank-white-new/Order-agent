from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db.models import HandoffCase, HandoffEvent, OrderEvent
from app.domain.enums import (
    DecisionClass,
    HandoffActorType,
    HandoffFailureCode,
    HandoffReasonCode,
    HandoffStatus,
)
from app.domain.errors import database_write_failed, handoff_not_found, invalid_handoff_transition, safety_session_not_found
from app.domain.safety import SafetyDecision
from app.services.handoff_provider import HandoffProvider, HandoffProviderResult
from app.services.handoff_summary_service import HandoffSummaryService
from app.services.safety_audit import log_safety_event, validate_safe_payload
from app.services.tenant_service import TenantService
from app.state.session_state import SessionState


ALLOWED_TRANSITIONS = {
    HandoffStatus.NOT_REQUIRED: {HandoffStatus.REQUESTED},
    HandoffStatus.REQUESTED: {HandoffStatus.PENDING, HandoffStatus.FAILED, HandoffStatus.CANCELLED},
    HandoffStatus.PENDING: {
        HandoffStatus.SIMULATED_AGENT_ASSIGNED,
        HandoffStatus.FAILED,
        HandoffStatus.CANCELLED,
    },
    HandoffStatus.SIMULATED_AGENT_ASSIGNED: {
        HandoffStatus.SIMULATED_AGENT_CONNECTED,
        HandoffStatus.FAILED,
        HandoffStatus.CANCELLED,
    },
    HandoffStatus.SIMULATED_AGENT_CONNECTED: {
        HandoffStatus.RESOLVED,
        HandoffStatus.FAILED,
        HandoffStatus.CANCELLED,
    },
    HandoffStatus.RESOLVED: set(),
    HandoffStatus.FAILED: set(),
    HandoffStatus.CANCELLED: set(),
}

CRITICAL_REASONS = {
    HandoffReasonCode.SEVERE_ALLERGY.value,
    HandoffReasonCode.CROSS_CONTAMINATION.value,
    HandoffReasonCode.ABUSE_OR_SECURITY.value,
}
HIGH_REASONS = {
    HandoffReasonCode.COMPLAINT.value,
    HandoffReasonCode.REFUND_REQUEST.value,
    HandoffReasonCode.PAYMENT_DISPUTE.value,
    HandoffReasonCode.REGULATED_ITEM.value,
    HandoffReasonCode.SYSTEM_FAILURE.value,
}


class HandoffService:
    def __init__(
        self,
        uow_factory,
        tenant_service: TenantService,
        provider: HandoffProvider,
        summary_service: HandoffSummaryService | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.tenant_service = tenant_service
        self.provider = provider
        self.summary_service = summary_service or HandoffSummaryService()

    def request_handoff(
        self,
        *,
        session_key: str,
        state: SessionState,
        decision: SafetyDecision,
        trace_id: str,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
    ) -> dict[str, Any]:
        if decision.classification != DecisionClass.HANDOFF or decision.reason_code is None:
            raise ValueError("request_handoff requires a HANDOFF safety decision")
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        try:
            public_id, created = self._create_or_reuse(
                tenant=tenant,
                session_key=session_key,
                decision=decision,
                trace_id=trace_id,
            )
        except IntegrityError:
            public_id, created = self._active_after_race(tenant, session_key)
        if not created:
            return self.get(public_id, tenant.restaurant_code, tenant.branch_code)

        try:
            with self.uow_factory() as uow:
                case = self._get_scoped(uow, public_id, tenant)
                session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
                if session is None:
                    raise safety_session_not_found()
                order = uow.orders.get(case.order_id, tenant.restaurant_id, tenant.branch_id) if case.order_id else None
                items = uow.orders.list_items(order.id) if order else ()
                case.summary_json = self.summary_service.build(
                    case=case,
                    tenant=tenant,
                    state=state,
                    order=order,
                    order_items=items,
                )
                result = self.provider.request_handoff(case)
                self._apply_transition(uow, case, result, HandoffActorType.SIMULATION_PROVIDER)
        except Exception:
            self._mark_summary_failure(public_id, tenant)
        return self.get(public_id, tenant.restaurant_code, tenant.branch_code)

    def get(
        self,
        public_id: str,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            case = self._get_scoped(uow, public_id, tenant, session_key)
            events = uow.handoffs.list_events(case.id)
            return self._serialize(case, events)

    def simulate_assign(
        self,
        public_id: str,
        restaurant_code: str | None,
        branch_code: str | None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        return self._provider_transition(
            public_id,
            restaurant_code,
            branch_code,
            "simulate_assign",
            session_key=session_key,
        )

    def simulate_connect(
        self,
        public_id: str,
        restaurant_code: str | None,
        branch_code: str | None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        return self._provider_transition(
            public_id,
            restaurant_code,
            branch_code,
            "simulate_connect",
            session_key=session_key,
        )

    def simulate_fail(
        self,
        public_id: str,
        failure_code: HandoffFailureCode,
        restaurant_code: str | None,
        branch_code: str | None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        return self._provider_transition(
            public_id,
            restaurant_code,
            branch_code,
            "simulate_fail",
            failure_code,
            session_key=session_key,
        )

    def resolve(
        self,
        public_id: str,
        resolution: dict[str, Any],
        restaurant_code: str | None,
        branch_code: str | None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        validate_safe_payload(resolution)
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            case = self._get_scoped(uow, public_id, tenant, session_key)
            result = self.provider.resolve(case, resolution)
            self._apply_transition(uow, case, result, HandoffActorType.SIMULATION_PROVIDER)
        return self.get(public_id, tenant.restaurant_code, tenant.branch_code, session_key)

    def cancel(
        self,
        public_id: str,
        restaurant_code: str | None,
        branch_code: str | None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            case = self._get_scoped(uow, public_id, tenant, session_key)
            result = self.provider.cancel_handoff(case)
            self._apply_transition(uow, case, result, HandoffActorType.CUSTOMER)
        return self.get(public_id, tenant.restaurant_code, tenant.branch_code, session_key)

    def _provider_transition(
        self,
        public_id: str,
        restaurant_code: str | None,
        branch_code: str | None,
        provider_method: str,
        *args,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            case = self._get_scoped(uow, public_id, tenant, session_key)
            method = getattr(self.provider, provider_method, None)
            if method is None:
                raise invalid_handoff_transition(case.status, provider_method)
            result = method(case, *args)
            self._apply_transition(uow, case, result, HandoffActorType.SIMULATION_PROVIDER)
        return self.get(public_id, tenant.restaurant_code, tenant.branch_code, session_key)

    def _create_or_reuse(self, *, tenant, session_key: str, decision: SafetyDecision, trace_id: str) -> tuple[str, bool]:
        with self.uow_factory() as uow:
            session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
            if session is None:
                raise safety_session_not_found()
            active = uow.handoffs.get_active(session.id, for_update=True)
            if active is not None:
                if active.reason_code != decision.reason_code:
                    old_reason = active.reason_code
                    active.reason_code = decision.reason_code
                    active.priority = self._max_priority(active.priority, self._priority(decision.reason_code))
                    active.risk_ids_json = sorted(set(active.risk_ids_json) | set(decision.risk_ids))
                    active.blocked_actions_json = sorted(
                        set(active.blocked_actions_json) | set(decision.blocked_actions)
                    )
                    if active.summary_json:
                        active.summary_json["handoffReasonCode"] = active.reason_code
                        active.summary_json["riskIds"] = active.risk_ids_json
                        active.summary_json["blockedActions"] = active.blocked_actions_json
                    self._add_event(
                        uow,
                        active,
                        "HANDOFF_RISK_UPDATED",
                        HandoffActorType.ORCHESTRATOR,
                        {"previousReasonCode": old_reason, "reasonCode": active.reason_code},
                    )
                return active.public_id, False
            order = uow.orders.get_latest_for_session(session.id, tenant.restaurant_id, tenant.branch_id)
            public_id = f"SIM-HO-{uuid4().hex[:20].upper()}"
            case = HandoffCase(
                public_id=public_id,
                restaurant_id=tenant.restaurant_id,
                branch_id=tenant.branch_id,
                session_id=session.id,
                order_id=order.id if order else None,
                status=HandoffStatus.REQUESTED.value,
                reason_code=decision.reason_code,
                priority=self._priority(decision.reason_code),
                decision_classification=DecisionClass.HANDOFF.value,
                risk_ids_json=list(decision.risk_ids),
                blocked_actions_json=list(decision.blocked_actions),
                summary_version=self.summary_service.VERSION,
                trace_id=trace_id,
                is_synthetic=True,
            )
            uow.handoffs.add(case)
            uow.handoffs.flush()
            self._add_event(
                uow,
                case,
                "HANDOFF_REQUESTED",
                HandoffActorType.ORCHESTRATOR,
                {"reasonCode": decision.reason_code, "priority": case.priority},
            )
            if order is not None:
                order.safety_hold = True
                order.safety_hold_reason = decision.reason_code
                confirmation = uow.orders.get_confirmation(order.id, order.draft_version)
                if confirmation is not None and confirmation.invalidated_at is None:
                    confirmation.invalidated_at = datetime.now(timezone.utc)
            self._log(case, "HANDOFF_REQUESTED")
            return public_id, True

    def _active_after_race(self, tenant, session_key: str) -> tuple[str, bool]:
        with self.uow_factory() as uow:
            session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
            if session is None:
                raise safety_session_not_found()
            active = uow.handoffs.get_active(session.id)
            if active is None:
                raise database_write_failed()
            return active.public_id, False

    def _apply_transition(
        self,
        uow,
        case: HandoffCase,
        result: HandoffProviderResult,
        actor: HandoffActorType,
    ) -> None:
        current = HandoffStatus(case.status)
        target = result.status
        if target not in ALLOWED_TRANSITIONS[current]:
            raise invalid_handoff_transition(current.value, target.value)
        now = datetime.now(timezone.utc)
        case.status = target.value
        if target == HandoffStatus.SIMULATED_AGENT_ASSIGNED:
            case.assigned_at = now
        elif target == HandoffStatus.SIMULATED_AGENT_CONNECTED:
            case.connected_at = now
        elif target == HandoffStatus.RESOLVED:
            if not result.resolution:
                raise ValueError("A simulated resolution result is required")
            validate_safe_payload(result.resolution)
            case.resolution_json = result.resolution
            case.resolved_at = now
            if result.resolution.get("draftChanged") and case.order_id:
                order = uow.orders.get(case.order_id, case.restaurant_id, case.branch_id)
                if order is not None:
                    previous_status = order.status
                    order.draft_version += 1
                    order.status = "DRAFT"
                    order.safety_hold = True
                    uow.orders.add(
                        OrderEvent(
                            order_id=order.id,
                            sequence_number=uow.orders.next_event_sequence(order.id),
                            event_type="ORDER_SIMULATED_HANDOFF_DRAFT_CHANGED",
                            payload_json={
                                "previousStatus": previous_status,
                                "newDraftVersion": order.draft_version,
                                "synthetic": True,
                            },
                            actor_type="SYSTEM",
                        )
                    )
        elif target == HandoffStatus.FAILED:
            if result.failure_code is None:
                raise ValueError("A handoff failure code is required")
            case.failure_code = result.failure_code.value
            case.failed_at = now
        elif target == HandoffStatus.CANCELLED:
            case.failure_code = HandoffFailureCode.CASE_CANCELLED.value
        payload = {"fromStatus": current.value, "toStatus": target.value}
        if result.failure_code:
            payload["failureCode"] = result.failure_code.value
        if result.resolution:
            payload["resolutionCode"] = result.resolution.get("resolutionCode", "SIMULATED_RESOLUTION")
            payload["draftChanged"] = bool(result.resolution.get("draftChanged", False))
        self._add_event(uow, case, f"HANDOFF_{target.value}", actor, payload)
        self._log(case, f"HANDOFF_{target.value}")

    def _mark_summary_failure(self, public_id: str, tenant) -> None:
        with self.uow_factory() as uow:
            case = self._get_scoped(uow, public_id, tenant)
            if HandoffStatus(case.status) not in {HandoffStatus.REQUESTED, HandoffStatus.PENDING}:
                return
            result = HandoffProviderResult(
                HandoffStatus.FAILED,
                failure_code=HandoffFailureCode.SYSTEM_ERROR,
            )
            self._apply_transition(uow, case, result, HandoffActorType.SYSTEM)

    def _add_event(self, uow, case: HandoffCase, event_type: str, actor: HandoffActorType, payload: dict) -> None:
        validate_safe_payload(payload)
        uow.handoffs.add(
            HandoffEvent(
                handoff_case_id=case.id,
                sequence_number=uow.handoffs.next_event_sequence(case.id),
                event_type=event_type,
                actor_type=actor.value,
                payload_json=payload,
            )
        )

    @staticmethod
    def _get_scoped(uow, public_id: str, tenant, session_key: str | None = None) -> HandoffCase:
        case = uow.handoffs.get_scoped(public_id, tenant.restaurant_id, tenant.branch_id)
        if case is None:
            raise handoff_not_found()
        if session_key is not None:
            session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
            if session is None or case.session_id != session.id:
                raise handoff_not_found()
        return case

    @staticmethod
    def _priority(reason_code: str) -> str:
        if reason_code in CRITICAL_REASONS:
            return "CRITICAL"
        if reason_code in HIGH_REASONS:
            return "HIGH"
        return "NORMAL"

    @staticmethod
    def _max_priority(current: str, new: str) -> str:
        ranking = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "CRITICAL": 3}
        return current if ranking[current] >= ranking[new] else new

    @staticmethod
    def _serialize(case: HandoffCase, events) -> dict[str, Any]:
        return {
            "handoffId": case.public_id,
            "status": case.status,
            "reasonCode": case.reason_code,
            "priority": case.priority,
            "decisionClassification": case.decision_classification,
            "riskIds": list(case.risk_ids_json),
            "blockedActions": list(case.blocked_actions_json),
            "summaryVersion": case.summary_version,
            "summary": case.summary_json,
            "failureCode": case.failure_code,
            "resolution": case.resolution_json,
            "isSynthetic": case.is_synthetic,
            "simulationNotice": "模拟人工接管，不是真实人工",
            "events": [
                {
                    "sequenceNumber": event.sequence_number,
                    "eventType": event.event_type,
                    "actorType": event.actor_type,
                    "payload": event.payload_json,
                    "occurredAt": event.occurred_at.isoformat(),
                }
                for event in events
            ],
        }

    @staticmethod
    def _log(case: HandoffCase, event_type: str) -> None:
        log_safety_event(
            trace_id=case.trace_id,
            session_id=case.session_id,
            restaurant_id=case.restaurant_id,
            branch_id=case.branch_id,
            order_id=case.order_id or "none",
            handoff_id=case.public_id,
            decision_classification=case.decision_classification,
            reason_code=case.reason_code,
            event_type=event_type,
        )
