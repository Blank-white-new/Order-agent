from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IdempotencyRecord, Order, OrderConfirmation, OrderEvent, OrderItem


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity) -> None:
        self.session.add(entity)

    def flush(self) -> None:
        self.session.flush()

    def get(self, order_id: int, restaurant_id: int, branch_id: int) -> Order | None:
        return self.session.scalar(
            select(Order).where(Order.id == order_id, Order.restaurant_id == restaurant_id, Order.branch_id == branch_id)
        )

    def get_by_public_id(self, public_id: str, restaurant_id: int, branch_id: int) -> Order | None:
        return self.session.scalar(
            select(Order).where(
                Order.public_id == public_id,
                Order.restaurant_id == restaurant_id,
                Order.branch_id == branch_id,
            )
        )

    def get_latest_for_session(self, session_id: int, restaurant_id: int, branch_id: int) -> Order | None:
        return self.session.scalar(
            select(Order)
            .where(
                Order.session_id == session_id,
                Order.restaurant_id == restaurant_id,
                Order.branch_id == branch_id,
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(1)
        )

    def list_items(self, order_id: int) -> list[OrderItem]:
        return list(self.session.scalars(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)))

    def get_confirmation(self, order_id: int, draft_version: int) -> OrderConfirmation | None:
        return self.session.scalar(
            select(OrderConfirmation).where(
                OrderConfirmation.order_id == order_id,
                OrderConfirmation.draft_version == draft_version,
            )
        )

    def next_event_sequence(self, order_id: int) -> int:
        current = self.session.scalar(select(func.max(OrderEvent.sequence_number)).where(OrderEvent.order_id == order_id))
        return int(current or 0) + 1


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, restaurant_id: int, branch_id: int, scope: str, key: str) -> IdempotencyRecord | None:
        return self.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.restaurant_id == restaurant_id,
                IdempotencyRecord.branch_id == branch_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idempotency_key == key,
            )
        )

    def add(self, entity: IdempotencyRecord) -> None:
        self.session.add(entity)
