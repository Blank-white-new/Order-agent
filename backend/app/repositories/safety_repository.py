from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    HandoffCase,
    HandoffEvent,
    SafetyDecisionRecord,
    SafetySessionCounter,
)


ACTIVE_HANDOFF_STATUSES = (
    "REQUESTED",
    "PENDING",
    "SIMULATED_AGENT_ASSIGNED",
    "SIMULATED_AGENT_CONNECTED",
)


class SafetyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity) -> None:
        self.session.add(entity)

    def get_counters(self, session_id: int) -> SafetySessionCounter | None:
        return self.session.scalar(
            select(SafetySessionCounter).where(SafetySessionCounter.session_id == session_id)
        )

    def list_decisions(self, session_id: int) -> list[SafetyDecisionRecord]:
        return list(
            self.session.scalars(
                select(SafetyDecisionRecord)
                .where(SafetyDecisionRecord.session_id == session_id)
                .order_by(SafetyDecisionRecord.id)
            )
        )


class HandoffRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity) -> None:
        self.session.add(entity)

    def flush(self) -> None:
        self.session.flush()

    def get_active(self, session_id: int, *, for_update: bool = False) -> HandoffCase | None:
        statement = select(HandoffCase).where(
            HandoffCase.session_id == session_id,
            HandoffCase.status.in_(ACTIVE_HANDOFF_STATUSES),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_scoped(
        self,
        public_id: str,
        restaurant_id: int,
        branch_id: int,
        *,
        for_update: bool = False,
    ) -> HandoffCase | None:
        statement = select(HandoffCase).where(
            HandoffCase.public_id == public_id,
            HandoffCase.restaurant_id == restaurant_id,
            HandoffCase.branch_id == branch_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def claim_cancellation(self, case_id: int) -> bool:
        result = self.session.execute(
            update(HandoffCase)
            .where(
                HandoffCase.id == case_id,
                HandoffCase.status.in_(ACTIVE_HANDOFF_STATUSES),
            )
            .values(status="CANCELLED", failure_code="CASE_CANCELLED")
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def next_event_sequence(self, case_id: int) -> int:
        current = self.session.scalar(
            select(func.max(HandoffEvent.sequence_number)).where(HandoffEvent.handoff_case_id == case_id)
        )
        return int(current or 0) + 1

    def list_events(self, case_id: int) -> list[HandoffEvent]:
        return list(
            self.session.scalars(
                select(HandoffEvent)
                .where(HandoffEvent.handoff_case_id == case_id)
                .order_by(HandoffEvent.sequence_number)
            )
        )
