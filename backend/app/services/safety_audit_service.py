from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.db.models import SafetyDecisionRecord, SafetySessionCounter
from app.domain.errors import safety_session_not_found
from app.domain.safety import SafetyCounters, SafetyDecision, SafetyEvaluationContext
from app.services.safety_audit import log_safety_event
from app.services.safety_decision_service import SafetyDecisionService
from app.services.tenant_service import TenantService


@dataclass(frozen=True)
class RecordedSafetyDecision:
    public_id: str
    trace_id: str
    decision: SafetyDecision
    counters: SafetyCounters


class SafetyAuditService:
    def __init__(self, uow_factory, tenant_service: TenantService, decision_service: SafetyDecisionService) -> None:
        self.uow_factory = uow_factory
        self.tenant_service = tenant_service
        self.decision_service = decision_service

    def evaluate_and_record(
        self,
        *,
        session_key: str,
        context: SafetyEvaluationContext,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        trace_id: str | None = None,
    ) -> RecordedSafetyDecision:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        trace_id = trace_id or f"SIM-TRACE-{uuid4().hex}"
        public_id = f"SIM-SD-{uuid4().hex[:20].upper()}"
        with self.uow_factory() as uow:
            session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
            if session is None:
                raise safety_session_not_found()
            counter = uow.safety.get_counters(session.id)
            if counter is None:
                counter = SafetySessionCounter(
                    session_id=session.id,
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                    consecutive_low_confidence=0,
                    consecutive_misunderstandings=0,
                    consecutive_corrections=0,
                    confirmation_failures=0,
                    is_synthetic=True,
                )
                uow.safety.add(counter)
            self._advance_counters(counter, context)
            counters = self._as_domain_counters(counter)
            decision = self.decision_service.evaluate(
                SafetyEvaluationContext(
                    signals=context.signals,
                    requested_action=context.requested_action,
                    required_confirmations=context.required_confirmations,
                    confidence=context.confidence,
                    counters=counters,
                    deterministic_input=context.deterministic_input,
                    risk_ids=context.risk_ids,
                    metric_ids=context.metric_ids,
                )
            )
            order = uow.orders.get_latest_for_session(session.id, tenant.restaurant_id, tenant.branch_id)
            uow.safety.add(
                SafetyDecisionRecord(
                    public_id=public_id,
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                    session_id=session.id,
                    order_id=order.id if order else None,
                    classification=decision.classification.value,
                    reason_code=decision.reason_code,
                    explanation_code=decision.explanation_code,
                    confidence_summary_json=context.confidence.summary(),
                    required_confirmations_json=list(decision.required_confirmations),
                    risk_ids_json=list(decision.risk_ids),
                    blocked_actions_json=list(decision.blocked_actions),
                    metric_ids_json=list(decision.metric_ids),
                    trace_id=trace_id,
                    is_synthetic=True,
                )
            )
        log_safety_event(
            trace_id=trace_id,
            session_id=session.id,
            restaurant_id=tenant.restaurant_code,
            branch_id=tenant.branch_code,
            order_id="present" if order else "none",
            handoff_id="none",
            decision_classification=decision.classification.value,
            reason_code=decision.reason_code or "none",
            event_type="SAFETY_DECISION_RECORDED",
        )
        return RecordedSafetyDecision(public_id=public_id, trace_id=trace_id, decision=decision, counters=counters)

    def get_counters(
        self,
        *,
        session_key: str,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
    ) -> SafetyCounters:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
            if session is None:
                raise safety_session_not_found()
            counter = uow.safety.get_counters(session.id)
            return self._as_domain_counters(counter) if counter else SafetyCounters()

    def _advance_counters(self, counter: SafetySessionCounter, context: SafetyEvaluationContext) -> None:
        signals = set(context.signals)
        confidence = context.confidence.effective_overall
        if confidence is not None and confidence < self.decision_service.settings.confirm_threshold:
            counter.consecutive_low_confidence += 1
        elif confidence is not None or context.deterministic_input:
            counter.consecutive_low_confidence = 0
        if "MISUNDERSTANDING" in signals:
            counter.consecutive_misunderstandings += 1
        elif "UNDERSTOOD" in signals:
            counter.consecutive_misunderstandings = 0
        if "CORRECTION" in signals:
            counter.consecutive_corrections += 1
        elif "UNDERSTOOD" in signals:
            counter.consecutive_corrections = 0
        if "CONFIRMATION_FAILED" in signals:
            counter.confirmation_failures += 1
        elif "CONFIRMATION_SUCCEEDED" in signals:
            counter.confirmation_failures = 0

    @staticmethod
    def _as_domain_counters(counter: SafetySessionCounter | None) -> SafetyCounters:
        if counter is None:
            return SafetyCounters()
        return SafetyCounters(
            consecutive_low_confidence=counter.consecutive_low_confidence,
            consecutive_misunderstandings=counter.consecutive_misunderstandings,
            consecutive_corrections=counter.consecutive_corrections,
            confirmation_failures=counter.confirmation_failures,
        )
