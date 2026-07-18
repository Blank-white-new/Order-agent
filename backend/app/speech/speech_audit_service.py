from __future__ import annotations

from uuid import uuid4

from app.db.models import SpeechTurnRecord
from app.domain.errors import safety_session_not_found


class SpeechAuditService:
    """Persists allow-listed metadata only; audio and transcripts are excluded."""

    def __init__(self, uow_factory, tenant_service) -> None:
        self.uow_factory = uow_factory
        self.tenant_service = tenant_service

    def record(
        self,
        *,
        session_id: str,
        restaurant_code: str,
        branch_code: str,
        direction: str,
        audio,
        trace_id: str,
        outcome: str,
        reason_code: str | None,
        audio_sha256: str,
        duration_ms: int | None,
        transcript=None,
        text_result=None,
    ) -> str:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        text_result = text_result or {}
        raw_state = text_result.get("raw_state")
        confidence = None if transcript is None else transcript.confidence
        with self.uow_factory() as uow:
            session = uow.sessions.get(session_id, tenant.restaurant_id, tenant.branch_id)
            if session is None:
                raise safety_session_not_found()
            order = uow.orders.get_latest_for_session(
                session.id,
                tenant.restaurant_id,
                tenant.branch_id,
            )
            public_id = f"SIM-ST-{uuid4().hex[:20].upper()}"
            uow.speech.add(
                SpeechTurnRecord(
                    public_id=public_id,
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                    session_id=session.id,
                    order_id=order.id if order else None,
                    direction=direction,
                    provider_name=(transcript.provider_name if transcript else "replay"),
                    provider_mode=(transcript.provider_mode.value if transcript else "REPLAY"),
                    audio_encoding=audio.encoding.value,
                    sample_rate_hz=audio.sample_rate_hz,
                    duration_ms=duration_ms,
                    audio_sha256=audio_sha256,
                    fixture_id=audio.fixture_id,
                    detected_locale=(
                        text_result.get("detected_locale")
                        or (transcript.locale if transcript else None)
                    ),
                    response_locale=text_result.get("response_locale"),
                    confidence_bucket=self._confidence_bucket(confidence),
                    decision_classification=getattr(raw_state, "safety_classification", None),
                    reason_code=reason_code or getattr(raw_state, "safety_reason_code", None),
                    outcome=outcome,
                    trace_id=trace_id,
                    is_synthetic=True,
                )
            )
        return public_id

    @staticmethod
    def _confidence_bucket(confidence: float | None) -> str | None:
        if confidence is None:
            return None
        if confidence >= 0.85:
            return "HIGH"
        if confidence >= 0.65:
            return "MEDIUM"
        return "LOW"
