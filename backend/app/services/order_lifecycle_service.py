from __future__ import annotations

from app.db.models import Order, OrderEvent
from app.domain.enums import ActorType, OrderStatus
from app.domain.errors import invalid_order_transition, safety_hold_active


ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.CUSTOMER_CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CUSTOMER_CONFIRMED: {OrderStatus.SUBMISSION_STARTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMISSION_STARTED: {OrderStatus.MERCHANT_PENDING, OrderStatus.SUBMISSION_FAILED, OrderStatus.CANCELLED},
    OrderStatus.MERCHANT_PENDING: {OrderStatus.MERCHANT_ACCEPTED, OrderStatus.MERCHANT_REJECTED, OrderStatus.CANCELLED},
    OrderStatus.MERCHANT_ACCEPTED: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.MERCHANT_REJECTED: {OrderStatus.CANCELLED},
    OrderStatus.SUBMISSION_FAILED: {OrderStatus.CANCELLED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.COMPLETED: set(),
}


class OrderLifecycleService:
    def validate(self, current: str | OrderStatus, target: str | OrderStatus) -> None:
        current_status = OrderStatus(current)
        target_status = OrderStatus(target)
        if target_status not in ALLOWED_TRANSITIONS[current_status]:
            raise invalid_order_transition(current_status.value, target_status.value)

    def transition(
        self,
        uow,
        order: Order,
        target: str | OrderStatus,
        *,
        actor_type: str | ActorType,
        payload: dict | None = None,
        merchant_fixture: bool = False,
    ) -> Order:
        target_status = OrderStatus(target)
        if order.safety_hold and target_status in {
            OrderStatus.SUBMISSION_STARTED,
            OrderStatus.MERCHANT_PENDING,
            OrderStatus.MERCHANT_ACCEPTED,
        }:
            raise safety_hold_active()
        if target_status in {OrderStatus.MERCHANT_PENDING, OrderStatus.MERCHANT_ACCEPTED, OrderStatus.MERCHANT_REJECTED}:
            if not merchant_fixture or not order.is_synthetic:
                raise invalid_order_transition(order.status, target_status.value)
        self.validate(order.status, target_status)
        previous = order.status
        order.status = target_status.value
        sequence = uow.orders.next_event_sequence(order.id)
        uow.orders.add(
            OrderEvent(
                order_id=order.id,
                sequence_number=sequence,
                event_type=f"ORDER_{target_status.value}",
                payload_json={"previousStatus": previous, **(payload or {})},
                actor_type=ActorType(actor_type).value,
            )
        )
        return order
