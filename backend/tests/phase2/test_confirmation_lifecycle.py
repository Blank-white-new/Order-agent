from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.agents.orchestrator import OrchestratorAgent
from app.db.models import Order, OrderConfirmation, OrderEvent
from app.domain.enums import ActorType, OrderStatus
from app.domain.errors import DomainError
from app.services.menu_service import MenuService
from app.services.order_lifecycle_service import OrderLifecycleService
from app.services.text_entry_service import TextEntryService
from .helpers import persisted_state


def _draft_order(context) -> str:
    key = "lifecycle-" + uuid.uuid4().hex
    context.session_store.get(key)
    tenant = context.tenant_service.resolve()
    with context.uow_factory() as uow:
        session_row = uow.sessions.find_any_tenant(key)
        order = Order(
            public_id="SIM-" + uuid.uuid4().hex[:16].upper(),
            restaurant_id=tenant.restaurant_id,
            branch_id=tenant.branch_id,
            session_id=session_row.id,
            customer_id=None,
            status="DRAFT",
            draft_version=1,
            currency="HKD",
            subtotal_minor=0,
            delivery_fee_minor=0,
            total_minor=0,
            fulfillment_type="pickup",
            is_synthetic=True,
        )
        uow.orders.add(order)
        uow.flush()
        return order.public_id


def _transition_path(context, path: list[OrderStatus], *, merchant_fixture: bool = False) -> Order:
    public_id = _draft_order(context)
    tenant = context.tenant_service.resolve()
    lifecycle = OrderLifecycleService()
    with context.uow_factory() as uow:
        order = uow.orders.get_by_public_id(public_id, tenant.restaurant_id, tenant.branch_id)
        for target in path:
            lifecycle.transition(
                uow,
                order,
                target,
                actor_type=ActorType.MERCHANT_FIXTURE if merchant_fixture else ActorType.SYSTEM,
                merchant_fixture=merchant_fixture,
            )
        uow.flush()
        return order


@pytest.mark.parametrize(
    "path",
    [
        [OrderStatus.CUSTOMER_CONFIRMED],
        [OrderStatus.CANCELLED],
        [OrderStatus.CUSTOMER_CONFIRMED, OrderStatus.SUBMISSION_STARTED],
        [OrderStatus.CUSTOMER_CONFIRMED, OrderStatus.SUBMISSION_STARTED, OrderStatus.SUBMISSION_FAILED],
        [OrderStatus.CUSTOMER_CONFIRMED, OrderStatus.CANCELLED],
    ],
)
def test_non_merchant_allowed_lifecycle_paths(phase2, path):
    assert _transition_path(phase2, path).status == path[-1].value


@pytest.mark.parametrize(
    "path",
    [
        [OrderStatus.CUSTOMER_CONFIRMED, OrderStatus.SUBMISSION_STARTED, OrderStatus.MERCHANT_PENDING],
        [
            OrderStatus.CUSTOMER_CONFIRMED,
            OrderStatus.SUBMISSION_STARTED,
            OrderStatus.MERCHANT_PENDING,
            OrderStatus.MERCHANT_ACCEPTED,
        ],
        [
            OrderStatus.CUSTOMER_CONFIRMED,
            OrderStatus.SUBMISSION_STARTED,
            OrderStatus.MERCHANT_PENDING,
            OrderStatus.MERCHANT_REJECTED,
        ],
        [
            OrderStatus.CUSTOMER_CONFIRMED,
            OrderStatus.SUBMISSION_STARTED,
            OrderStatus.MERCHANT_PENDING,
            OrderStatus.MERCHANT_ACCEPTED,
            OrderStatus.COMPLETED,
        ],
    ],
)
def test_merchant_states_exist_only_for_explicit_synthetic_fixtures(phase2, path):
    assert _transition_path(phase2, path, merchant_fixture=True).status == path[-1].value


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ([], OrderStatus.MERCHANT_ACCEPTED),
        ([OrderStatus.CUSTOMER_CONFIRMED], OrderStatus.MERCHANT_ACCEPTED),
        ([OrderStatus.CUSTOMER_CONFIRMED, OrderStatus.SUBMISSION_STARTED], OrderStatus.MERCHANT_PENDING),
    ],
)
def test_illegal_or_unproven_merchant_transitions_are_rejected(phase2, path, target):
    public_id = _draft_order(phase2)
    tenant = phase2.tenant_service.resolve()
    lifecycle = OrderLifecycleService()
    with phase2.uow_factory() as uow:
        order = uow.orders.get_by_public_id(public_id, tenant.restaurant_id, tenant.branch_id)
        for step in path:
            lifecycle.transition(uow, order, step, actor_type=ActorType.SYSTEM)
        with pytest.raises(DomainError) as error:
            lifecycle.transition(uow, order, target, actor_type=ActorType.SYSTEM)
        assert error.value.code == "INVALID_ORDER_TRANSITION"


def test_confirmation_binds_draft_and_never_claims_merchant_acceptance(phase2):
    state = persisted_state(phase2, "confirmation-binding")
    result = phase2.order_service.confirm_order(session_key="confirmation-binding", state=state)
    assert result.lifecycle_status == "CUSTOMER_CONFIRMED"
    assert result.merchant_status == "NOT_INTEGRATED"
    assert result.public_id.startswith("SIM-")
    tenant = phase2.tenant_service.resolve()
    with phase2.uow_factory() as uow:
        order = uow.orders.get_by_public_id(result.public_id, tenant.restaurant_id, tenant.branch_id)
        confirmation = uow.orders.get_confirmation(order.id, order.draft_version)
        assert confirmation.draft_version == state.draft_version
        assert order.status != "MERCHANT_ACCEPTED"
        events = list(uow.session.scalars(select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.sequence_number)))
        assert [event.sequence_number for event in events] == list(range(1, len(events) + 1))


def test_invalidated_confirmation_is_stale_and_order_is_cancelled(phase2):
    state = persisted_state(phase2, "stale-confirmation")
    result = phase2.order_service.confirm_order(
        session_key="stale-confirmation", state=state, idempotency_key="stale-key"
    )
    new_version = phase2.order_service.invalidate_confirmation(
        result.public_id, "hk-sim-restaurant-a", "central"
    )
    assert new_version == state.draft_version + 1
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(
            session_key="stale-confirmation", state=state, idempotency_key="stale-key"
        )
    assert error.value.code == "CONFIRMATION_STALE"
    with phase2.database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.public_id == result.public_id))
        confirmation = session.scalar(select(OrderConfirmation).where(OrderConfirmation.order_id == order.id))
        assert order.status == "CANCELLED"
        assert confirmation.invalidated_at is not None


def test_question_does_not_create_confirmation(phase2):
    service = TextEntryService(
        store=phase2.session_store,
        orchestrator=OrchestratorAgent(menu_service=MenuService(database=phase2.database)),
    )
    import asyncio

    response = asyncio.run(service.handle_text_message("question-only", "鸡腿饭多少钱？"))
    assert response["trace"]["finalIntent"] == "ask_price"
    with phase2.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(OrderConfirmation)) == 0
