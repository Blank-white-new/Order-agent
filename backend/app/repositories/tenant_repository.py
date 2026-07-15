from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Branch, Restaurant
from app.repositories.records import TenantRecord


class TenantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_restaurant_by_code(self, code: str) -> Restaurant | None:
        return self.session.scalar(select(Restaurant).where(Restaurant.code == code, Restaurant.deleted_at.is_(None)))

    def get_branch(self, restaurant_id: int, code: str) -> Branch | None:
        return self.session.scalar(
            select(Branch).where(
                Branch.restaurant_id == restaurant_id,
                Branch.code == code,
                Branch.deleted_at.is_(None),
            )
        )

    def get_branch_by_id(self, branch_id: int) -> Branch | None:
        return self.session.get(Branch, branch_id)

    def as_record(self, restaurant: Restaurant, branch: Branch) -> TenantRecord:
        return TenantRecord(
            restaurant_id=restaurant.id,
            restaurant_code=restaurant.code,
            branch_id=branch.id,
            branch_code=branch.code,
            restaurant_timezone=restaurant.timezone,
            branch_timezone=branch.timezone,
            currency=restaurant.currency,
            is_simulation=restaurant.is_simulation,
        )
