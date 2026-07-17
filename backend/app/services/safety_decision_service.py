from __future__ import annotations

from app.domain.enums import DecisionClass, HandoffReasonCode, RefusalReasonCode
from app.domain.safety import SafetyDecision, SafetyEvaluationContext
from app.services.safety_policy_config import SafetyPolicySettings


HANDOFF_SIGNAL_TO_REASON = {reason.value: reason for reason in HandoffReasonCode}
REFUSAL_SIGNAL_TO_REASON = {reason.value: reason for reason in RefusalReasonCode}

CONFIRMATION_SIGNALS = {
    "FINAL_ORDER": "final_order",
    "ADDRESS": "address",
    "PHONE": "phone",
    "AMBIGUOUS_ITEM_CANDIDATES": "item",
    "AMBIGUOUS_QUANTITY_CANDIDATES": "quantity",
    "LARGE_MODIFICATION": "order_changes",
    "DELETE_ALL_ITEMS": "empty_order",
    "IMPORTANT_NOTE": "important_notes",
    "INFERRED_VALUE": "inferred_values",
    "DELIVERY_FEE": "delivery_fee",
    "ORDER_VERSION_CHANGED": "order_version",
}

DEFAULT_BLOCKED_ACTIONS = (
    "SUBMIT_TO_MERCHANT",
    "MARK_MERCHANT_ACCEPTED",
    "TAKE_PAYMENT",
)

REASON_PRIORITY = {reason.value: index for index, reason in enumerate(HandoffReasonCode)}
REFUSAL_PRIORITY = {reason.value: index for index, reason in enumerate(RefusalReasonCode)}


class SafetyDecisionService:
    """Deterministic policy engine. Natural-language parsing is deliberately out of scope."""

    def __init__(self, settings: SafetyPolicySettings | None = None) -> None:
        self.settings = settings or SafetyPolicySettings.from_env()

    def evaluate(self, context: SafetyEvaluationContext) -> SafetyDecision:
        signals = set(context.signals)
        confidence = context.confidence.effective_overall
        risk_ids = tuple(dict.fromkeys((*context.risk_ids, *self._risk_ids(signals))))
        metric_ids = tuple(dict.fromkeys((*context.metric_ids, *self._metric_ids(signals))))

        refusal_reasons = sorted(
            (REFUSAL_SIGNAL_TO_REASON[signal] for signal in signals if signal in REFUSAL_SIGNAL_TO_REASON),
            key=lambda reason: REFUSAL_PRIORITY[reason.value],
        )
        if refusal_reasons:
            return SafetyDecision(
                classification=DecisionClass.REFUSE,
                reason_code=refusal_reasons[0].value,
                confidence=confidence,
                required_confirmations=(),
                blocked_actions=(context.requested_action, *DEFAULT_BLOCKED_ACTIONS),
                risk_ids=risk_ids,
                metric_ids=metric_ids,
                explanation_code="SAFETY_OPERATION_REFUSED",
            )

        handoff_reasons = [
            HANDOFF_SIGNAL_TO_REASON[signal] for signal in signals if signal in HANDOFF_SIGNAL_TO_REASON
        ]
        if (
            context.counters.consecutive_misunderstandings >= self.settings.max_consecutive_misunderstandings
            or context.counters.consecutive_corrections >= self.settings.max_consecutive_misunderstandings
            or context.counters.consecutive_low_confidence >= self.settings.max_consecutive_misunderstandings
            or context.counters.confirmation_failures >= self.settings.max_confirmation_failures
        ):
            handoff_reasons.append(HandoffReasonCode.REPEATED_MISUNDERSTANDING)
        if handoff_reasons:
            reason = min(handoff_reasons, key=lambda item: REASON_PRIORITY[item.value])
            return SafetyDecision(
                classification=DecisionClass.HANDOFF,
                reason_code=reason.value,
                confidence=confidence,
                required_confirmations=(),
                blocked_actions=DEFAULT_BLOCKED_ACTIONS,
                risk_ids=risk_ids,
                metric_ids=metric_ids,
                explanation_code="SIMULATED_HANDOFF_REQUIRED",
            )

        required = list(context.required_confirmations)
        required.extend(CONFIRMATION_SIGNALS[signal] for signal in signals if signal in CONFIRMATION_SIGNALS)
        if context.confidence.contradictory_fields:
            required.extend(name.removesuffix("_confidence") for name in context.confidence.contradictory_fields)
        if not context.deterministic_input and confidence is None:
            required.append("intent")
        elif confidence is not None and confidence < self.settings.confirm_threshold:
            required.append("low_confidence_input")
        if required:
            return SafetyDecision(
                classification=DecisionClass.CONFIRM,
                reason_code=None,
                confidence=confidence,
                required_confirmations=tuple(dict.fromkeys(required)),
                blocked_actions=DEFAULT_BLOCKED_ACTIONS,
                risk_ids=risk_ids,
                metric_ids=metric_ids,
                explanation_code="EXPLICIT_CONFIRMATION_REQUIRED",
            )

        return SafetyDecision(
            classification=DecisionClass.AUTO_DRAFT,
            reason_code=None,
            confidence=confidence,
            required_confirmations=(),
            blocked_actions=DEFAULT_BLOCKED_ACTIONS,
            risk_ids=risk_ids,
            metric_ids=metric_ids,
            explanation_code="REVERSIBLE_DRAFT_OPERATION_ALLOWED",
        )

    @staticmethod
    def _risk_ids(signals: set[str]) -> tuple[str, ...]:
        risks: list[str] = []
        if {"SEVERE_ALLERGY", "CROSS_CONTAMINATION", "UNSUPPORTED_SAFETY_GUARANTEE"} & signals:
            risks.extend(("RISK-009", "RISK-011", "RISK-013"))
        if {"CROSS_TENANT_ACCESS", "UNAUTHORIZED_ORDER_ACCESS"} & signals:
            risks.extend(("RISK-026", "RISK-028", "RISK-030", "RISK-031"))
        if {"BYPASS_CONFIRMATION", "FORGE_MERCHANT_ACCEPTANCE"} & signals:
            risks.extend(("RISK-007", "RISK-008", "RISK-033"))
        if {"CARD_DATA_STORAGE", "INTERNAL_SECRET_EXTRACTION", "SECURITY_ATTACK", "ABUSE_OR_SECURITY"} & signals:
            risks.extend(("RISK-029", "RISK-037", "RISK-046"))
        return tuple(risks)

    @staticmethod
    def _metric_ids(signals: set[str]) -> tuple[str, ...]:
        metrics = ["METRIC-011", "METRIC-012"]
        if {"SEVERE_ALLERGY", "CROSS_CONTAMINATION"} & signals:
            metrics.extend(("METRIC-006", "METRIC-014"))
        if {"BYPASS_CONFIRMATION", "FINAL_ORDER"} & signals:
            metrics.extend(("METRIC-001", "METRIC-002"))
        if {"CROSS_TENANT_ACCESS", "UNAUTHORIZED_ORDER_ACCESS"} & signals:
            metrics.extend(("METRIC-004", "METRIC-005"))
        return tuple(metrics)
