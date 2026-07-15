from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BranchItemAvailability, DeliveryZone, OpeningHours


class OperationsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_hours(self, branch_id: int, weekday: int, local_date: date) -> list[OpeningHours]:
        return list(
            self.session.scalars(
                select(OpeningHours).where(
                    OpeningHours.branch_id == branch_id,
                    OpeningHours.weekday == weekday,
                    (OpeningHours.effective_date.is_(None) | (OpeningHours.effective_date == local_date)),
                )
            )
        )

    def get_zone(self, branch_id: int, code: str | None = None) -> DeliveryZone | None:
        statement = select(DeliveryZone).where(DeliveryZone.branch_id == branch_id, DeliveryZone.active.is_(True))
        if code:
            statement = statement.where(DeliveryZone.code == code)
        return self.session.scalar(statement.order_by(DeliveryZone.id))

    def get_availability(self, branch_id: int, menu_item_id: int) -> BranchItemAvailability | None:
        return self.session.scalar(
            select(BranchItemAvailability).where(
                BranchItemAvailability.branch_id == branch_id,
                BranchItemAvailability.menu_item_id == menu_item_id,
            )
        )
