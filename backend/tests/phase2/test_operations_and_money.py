from __future__ import annotations

from datetime import datetime, time, timezone

import pytest
from sqlalchemy import delete, select

from app.db.models import (
    BranchItemAvailability,
    MenuItem,
    ModifierOption,
    OpeningHours,
)
from app.domain.errors import DomainError
from app.services.menu_service import MenuService
from app.services.opening_hours_service import OpeningHoursService
from app.state.session_state import OrderItem
from .helpers import persisted_state


def test_branch_sold_out_item_is_hidden_only_for_that_branch(phase2):
    central = MenuService(restaurant_code="hk-sim-restaurant-a", branch_code="central", database=phase2.database)
    east = MenuService(restaurant_code="hk-sim-restaurant-a", branch_code="east", database=phase2.database)
    assert central.find_item_by_name("牛肉饭") is not None
    assert east.find_item_by_name("牛肉饭") is None


def test_final_confirmation_revalidates_sold_out_state_and_rolls_back(phase2):
    state = persisted_state(phase2, "sold-out-recheck")
    before = state.serializable()
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        item = session.scalar(select(MenuItem).where(MenuItem.code == "chicken_leg_rice"))
        availability = session.scalar(
            select(BranchItemAvailability).where(
                BranchItemAvailability.branch_id == tenant.branch_id,
                BranchItemAvailability.menu_item_id == item.id,
            )
        )
        availability.available = False
        availability.reason_code = "SYNTHETIC_TEST_SOLD_OUT"
        session.commit()
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(session_key="sold-out-recheck", state=state)
    assert error.value.code == "ITEM_SOLD_OUT"
    assert state.serializable() == before


def test_opening_hours_uses_branch_timezone_and_previous_day_for_cross_midnight(phase2):
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        session.execute(delete(OpeningHours).where(OpeningHours.branch_id == tenant.branch_id))
        session.add(
            OpeningHours(
                branch_id=tenant.branch_id,
                weekday=0,
                start_time=time(22, 0),
                end_time=time(2, 0),
                is_closed=False,
                metadata_json={"synthetic": True},
            )
        )
        session.commit()
    service = OpeningHoursService(phase2.uow_factory)
    assert service.is_branch_open(tenant.branch_id, datetime(2026, 7, 13, 14, 30, tzinfo=timezone.utc))
    assert service.is_branch_open(tenant.branch_id, datetime(2026, 7, 13, 17, 0, tzinfo=timezone.utc))
    assert not service.is_branch_open(tenant.branch_id, datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc))


def test_temporary_closure_overrides_previous_day_cross_midnight_slot(phase2):
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        session.execute(delete(OpeningHours).where(OpeningHours.branch_id == tenant.branch_id))
        session.add_all(
            [
                OpeningHours(
                    branch_id=tenant.branch_id,
                    weekday=0,
                    start_time=time(22),
                    end_time=time(2),
                    is_closed=False,
                ),
                OpeningHours(
                    branch_id=tenant.branch_id,
                    weekday=1,
                    start_time=time(0),
                    end_time=time(0),
                    is_closed=True,
                    effective_date=datetime(2026, 7, 14).date(),
                    reason_code="SYNTHETIC_CLOSURE",
                ),
            ]
        )
        session.commit()
    assert not OpeningHoursService(phase2.uow_factory).is_branch_open(
        tenant.branch_id, datetime(2026, 7, 13, 17, 0, tzinfo=timezone.utc)
    )


def test_authoritative_integer_minor_prices_modifier_and_delivery_fee(phase2):
    state = persisted_state(phase2, "money-order")
    state.fulfillment_type = "delivery"
    state.current_order[0].options = ["加饭"]
    phase2.session_store.set("money-order", state)
    with phase2.database.session_factory() as session:
        option = session.scalar(select(ModifierOption).where(ModifierOption.name == "加饭"))
        option.price_delta_minor = 250
        session.commit()
    result = phase2.order_service.confirm_order(session_key="money-order", state=state, idempotency_key="money")
    assert result.currency == "HKD"
    assert result.subtotal_minor == 2850
    assert result.delivery_fee_minor == 500
    assert result.total_minor == 3350
    assert all(isinstance(value, int) for value in [result.subtotal_minor, result.delivery_fee_minor, result.total_minor])
    tenant = phase2.tenant_service.resolve()
    with phase2.uow_factory() as uow:
        order = uow.orders.get_by_public_id(result.public_id, tenant.restaurant_id, tenant.branch_id)
        item = uow.orders.list_items(order.id)[0]
        assert item.unit_price_minor == 2850
        assert item.line_total_minor == 2850
        assert item.modifier_snapshot_json[0]["priceDeltaMinor"] == 250
        assert item.allergen_snapshot_json[0]["declaration"] == "UNKNOWN"


def test_client_price_is_ignored_and_currency_mismatch_is_rejected(phase2):
    state = persisted_state(phase2, "authority-price")
    state.current_order[0].price = 999999
    state.current_order[0].unit_price_minor = 1
    result = phase2.order_service.confirm_order(session_key="authority-price", state=state)
    assert result.subtotal_minor == 2600

    second = persisted_state(phase2, "currency-mismatch")
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        menu = MenuService(database=phase2.database)
        item_id = menu.find_item_by_name("鸡腿饭").menu_item_db_id
        session.get(MenuItem, item_id).currency = "USD"
        session.commit()
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(session_key="currency-mismatch", state=second)
    assert error.value.code == "CURRENCY_MISMATCH"
