from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Branch,
    BranchItemAvailability,
    MenuItem,
    MenuVersion,
    Order,
    Restaurant,
)
from app.domain.errors import DomainError
from app.services.menu_service import MenuService
from app.services.seed_service import seed_phase2_simulation_data
from .helpers import persisted_state


def test_seed_is_idempotent_and_contains_two_isolated_synthetic_tenants(phase2):
    second = seed_phase2_simulation_data(phase2.uow_factory)
    assert second.as_dict() == {
        "restaurants_created": 0,
        "branches_created": 0,
        "menu_versions_created": 0,
        "menu_items_created": 0,
    }
    with phase2.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Restaurant)) == 2
        assert session.scalar(select(func.count()).select_from(Branch)) == 4
        assert session.scalar(select(func.count()).select_from(MenuVersion)) == 2
        assert session.scalar(select(func.count()).select_from(MenuItem)) == 22
        assert session.scalar(select(func.count()).select_from(BranchItemAvailability)) == 44
        assert all(session.scalars(select(Restaurant.is_simulation)))


def test_default_tenant_and_price_differences_are_database_backed(phase2):
    default_tenant = phase2.tenant_service.resolve()
    assert (default_tenant.restaurant_code, default_tenant.branch_code) == ("hk-sim-restaurant-a", "central")
    menu_a = MenuService(database=phase2.database)
    menu_b = MenuService(restaurant_code="hk-sim-restaurant-b", branch_code="north", database=phase2.database)
    assert menu_a.get_item_price_minor("鸡腿饭") == 2600
    assert menu_b.get_item_price_minor("鸡腿饭") == 2800


def test_menu_and_sold_out_state_do_not_cross_tenants_or_branches(phase2):
    central = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    east = phase2.tenant_service.resolve("hk-sim-restaurant-a", "east")
    restaurant_b = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase2.uow_factory() as uow:
        b_item = uow.menus.get_item_by_code(restaurant_b.branch_id, "chicken_leg_rice")
        assert b_item is not None
        assert uow.menus.get_item_for_branch(central.branch_id, b_item.id) is None
        assert uow.menus.get_item_by_code(central.branch_id, "beef_rice").available is True
        assert uow.menus.get_item_by_code(east.branch_id, "beef_rice").available is False


def test_session_key_cannot_switch_restaurant_or_branch(phase2):
    phase2.session_store.get("bound-session", "hk-sim-restaurant-a", "central")
    for restaurant, branch in [
        ("hk-sim-restaurant-a", "east"),
        ("hk-sim-restaurant-b", "north"),
    ]:
        with pytest.raises(DomainError) as error:
            phase2.session_store.get("bound-session", restaurant, branch)
        assert error.value.code == "TENANT_CONTEXT_MISMATCH"


def test_order_repository_defaults_to_denying_other_tenants(phase2):
    state = persisted_state(phase2, "tenant-order")
    result = phase2.order_service.confirm_order(session_key="tenant-order", state=state, idempotency_key="tenant-order-key")
    tenant_a = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    tenant_b = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase2.uow_factory() as uow:
        assert uow.orders.get_by_public_id(result.public_id, tenant_a.restaurant_id, tenant_a.branch_id)
        assert uow.orders.get_by_public_id(result.public_id, tenant_b.restaurant_id, tenant_b.branch_id) is None


def test_database_rejects_cross_restaurant_active_menu_binding(phase2):
    tenant_a = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    tenant_b = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase2.database.session_factory() as session:
        branch = session.get(Branch, tenant_a.branch_id)
        other_menu = session.scalar(select(MenuVersion).where(MenuVersion.restaurant_id == tenant_b.restaurant_id))
        branch.active_menu_version_id = other_menu.id
        with pytest.raises(IntegrityError):
            session.commit()


def test_unknown_tenant_errors_are_stable_and_do_not_expose_database_details(phase2):
    with pytest.raises(DomainError) as error:
        phase2.tenant_service.resolve("missing-tenant", "central")
    assert error.value.code == "RESTAURANT_NOT_FOUND"
    assert "sqlite" not in error.value.message.lower()
    assert "select " not in error.value.message.lower()
