from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Allergen,
    Branch,
    BranchItemAvailability,
    ConversationSession,
    Customer,
    DeliveryZone,
    IdempotencyRecord,
    MenuItem,
    MenuItemAllergen,
    MenuItemModifierGroup,
    MenuVersion,
    ModifierGroup,
    ModifierOption,
    Order,
    OrderItem,
)
from app.domain.errors import DomainError
from app.services.menu_management_service import MenuManagementService
from .helpers import persisted_state


def _menu_item(session, restaurant_id: int, *, code: str | None = None) -> MenuItem:
    statement = select(MenuItem).join(MenuVersion).where(MenuVersion.restaurant_id == restaurant_id)
    if code is not None:
        statement = statement.where(MenuItem.code == code)
    return session.scalar(statement.order_by(MenuItem.id))


def _session_row(phase2, key: str, *, restaurant: str = "hk-sim-restaurant-a", branch: str = "central"):
    phase2.session_store.get(key, restaurant, branch)
    with phase2.database.session_factory() as session:
        return session.scalar(select(ConversationSession).where(ConversationSession.session_key == key))


def _order_values(tenant, session_id: int, **overrides) -> dict:
    values = {
        "public_id": f"SIM-AUDIT-{session_id}-{overrides.get('customer_id') or 0}-{overrides.get('delivery_zone_id') or 0}",
        "restaurant_id": tenant.restaurant_id,
        "branch_id": tenant.branch_id,
        "session_id": session_id,
        "customer_id": None,
        "status": "DRAFT",
        "draft_version": 1,
        "currency": "HKD",
        "subtotal_minor": 0,
        "delivery_fee_minor": 0,
        "total_minor": 0,
        "fulfillment_type": "pickup",
        "delivery_zone_id": None,
        "is_synthetic": True,
    }
    values.update(overrides)
    return values


def _add_modifier_group(
    phase2,
    *,
    item_code: str = "chicken_leg_rice",
    code: str,
    required: bool = False,
    minimum: int = 0,
    maximum: int = 1,
    options: list[tuple[str, bool]],
) -> list[str]:
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        item = _menu_item(session, tenant.restaurant_id, code=item_code)
        group = ModifierGroup(
            menu_version_id=item.menu_version_id,
            code=code,
            name=f"Synthetic {code}",
            required=required,
            min_selections=minimum,
            max_selections=maximum,
            sort_order=100,
            active=True,
        )
        session.add(group)
        session.flush()
        session.add(
            MenuItemModifierGroup(
                menu_item_id=item.id,
                modifier_group_id=group.id,
                menu_version_id=item.menu_version_id,
                sort_order=100,
            )
        )
        for index, (name, active) in enumerate(options):
            session.add(
                ModifierOption(
                    modifier_group_id=group.id,
                    code=f"{code}-{index + 1}",
                    name=name,
                    price_delta_minor=100 * (index + 1),
                    sort_order=index,
                    active=active,
                )
            )
        session.commit()
    return [name for name, _active in options]


def _confirm_with_options(phase2, key: str, options: list[str]):
    state = persisted_state(phase2, key)
    state.current_order[0].options = options
    phase2.session_store.set(key, state)
    return phase2.order_service.confirm_order(session_key=key, state=state)


def test_database_rejects_cross_restaurant_branch_item_availability(phase2):
    first = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    second = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase2.database.session_factory() as session:
        foreign_item = _menu_item(session, second.restaurant_id)
        session.add(
            BranchItemAvailability(
                branch_id=first.branch_id,
                restaurant_id=first.restaurant_id,
                menu_item_id=foreign_item.id,
                menu_version_id=foreign_item.menu_version_id,
                available=True,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_cross_version_item_modifier_group(phase2):
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        item = _menu_item(session, tenant.restaurant_id)
        version = MenuVersion(restaurant_id=tenant.restaurant_id, version_number=99, status="DRAFT")
        session.add(version)
        session.flush()
        group = ModifierGroup(
            menu_version_id=version.id,
            code="cross-version",
            name="Synthetic Cross Version",
            required=False,
            min_selections=0,
            max_selections=1,
            active=True,
        )
        session.add(group)
        session.flush()
        session.add(
            MenuItemModifierGroup(
                menu_item_id=item.id,
                modifier_group_id=group.id,
                menu_version_id=item.menu_version_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_cross_restaurant_item_allergen(phase2):
    first = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    second = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase2.database.session_factory() as session:
        item = _menu_item(session, first.restaurant_id)
        allergen = session.scalar(select(Allergen).where(Allergen.restaurant_id == second.restaurant_id))
        session.add(
            MenuItemAllergen(
                menu_item_id=item.id,
                menu_version_id=item.menu_version_id,
                allergen_id=allergen.id,
                restaurant_id=first.restaurant_id,
                declaration="UNKNOWN",
                source="synthetic-integrity-test",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_cross_restaurant_order_customer(phase2):
    first = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    second = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    session_row = _session_row(phase2, "cross-customer")
    with phase2.database.session_factory() as session:
        customer = Customer(
            restaurant_id=second.restaurant_id,
            external_reference="synthetic-cross-customer",
            is_synthetic=True,
        )
        session.add(customer)
        session.flush()
        session.add(Order(**_order_values(first, session_row.id, customer_id=customer.id)))
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_cross_branch_order_delivery_zone(phase2):
    central = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    east = phase2.tenant_service.resolve("hk-sim-restaurant-a", "east")
    session_row = _session_row(phase2, "cross-zone")
    with phase2.database.session_factory() as session:
        zone = session.scalar(select(DeliveryZone).where(DeliveryZone.branch_id == east.branch_id))
        session.add(
            Order(
                **_order_values(
                    central,
                    session_row.id,
                    fulfillment_type="delivery",
                    delivery_zone_id=zone.id,
                    delivery_fee_minor=zone.fee_minor,
                    total_minor=zone.fee_minor,
                )
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_order_item_with_unrelated_item_and_version(phase2):
    first = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    second = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    session_row = _session_row(phase2, "cross-order-item")
    with phase2.database.session_factory() as session:
        item = _menu_item(session, first.restaurant_id)
        foreign_version = session.scalar(
            select(MenuVersion).where(MenuVersion.restaurant_id == second.restaurant_id)
        )
        order = Order(**_order_values(first, session_row.id))
        session.add(order)
        session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                restaurant_id=first.restaurant_id,
                menu_item_id=item.id,
                menu_version_id=foreign_version.id,
                item_code_snapshot="synthetic-mismatch",
                item_name_snapshot="Synthetic Mismatch",
                unit_price_minor=100,
                quantity=1,
                modifier_snapshot_json=[],
                allergen_snapshot_json=[],
                line_total_minor=100,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_idempotency_branch_from_another_restaurant(phase2):
    first = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    second = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase2.database.session_factory() as session:
        session.add(
            IdempotencyRecord(
                restaurant_id=first.restaurant_id,
                branch_id=second.branch_id,
                scope="AUDIT",
                idempotency_key="synthetic-cross-tenant",
                request_fingerprint="0" * 64,
                resource_type="AUDIT",
                resource_id="synthetic",
                status="SUCCEEDED",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_same_session_key_in_two_tenants_without_leaking_context(phase2):
    first = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    second = phase2.tenant_service.resolve("hk-sim-restaurant-b", "north")
    phase2.session_store.get("globally-bound-session", "hk-sim-restaurant-a", "central")
    with phase2.database.session_factory() as session:
        session.add(
            ConversationSession(
                session_key="globally-bound-session",
                restaurant_id=second.restaurant_id,
                branch_id=second.branch_id,
                locale="zh-CN",
                state_json={},
                version=1,
                status="ACTIVE",
                is_synthetic=True,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    with pytest.raises(DomainError) as error:
        phase2.session_store.get("globally-bound-session", "hk-sim-restaurant-b", "north")
    assert error.value.code == "TENANT_CONTEXT_MISMATCH"
    assert first.restaurant_id != second.restaurant_id


def test_concurrent_session_creation_produces_one_global_session(phase2):
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=10)
        return phase2.session_store.get("concurrent-global-session")

    with ThreadPoolExecutor(max_workers=2) as executor:
        states = list(executor.map(lambda _index: create(), range(2)))
    assert all(state.persistence_version == 1 for state in states)
    with phase2.database.session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(ConversationSession).where(
                ConversationSession.session_key == "concurrent-global-session"
            )
        )
        assert count == 1


def test_database_rejects_two_published_versions_for_one_restaurant(phase2):
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        session.add(MenuVersion(restaurant_id=tenant.restaurant_id, version_number=99, status="PUBLISHED"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_concurrent_restaurant_wide_publication_has_one_winner_and_no_branch_gap(phase2):
    tenant = phase2.tenant_service.resolve()
    service = MenuManagementService(phase2.uow_factory)
    version_ids = [service.create_draft(tenant.restaurant_id).id for _index in range(2)]
    barrier = Barrier(2)
    seen_threads: set[int] = set()
    seen_lock = Lock()

    def synchronize_published_lookup(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower()
        if "from menu_versions" not in normalized or "menu_versions.status =" not in normalized:
            return
        thread_id = get_ident()
        with seen_lock:
            if thread_id in seen_threads:
                return
            seen_threads.add(thread_id)
        barrier.wait(timeout=10)

    event.listen(phase2.database.engine, "before_cursor_execute", synchronize_published_lookup)

    def publish(version_id: int):
        try:
            return ("PUBLISHED", service.publish(tenant.restaurant_id, version_id).id)
        except DomainError as error:
            return (error.code, version_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, version_ids))
    finally:
        event.remove(phase2.database.engine, "before_cursor_execute", synchronize_published_lookup)

    assert sorted(code for code, _version_id in results) == ["MENU_PUBLISH_CONFLICT", "PUBLISHED"]
    with phase2.database.session_factory() as session:
        published = list(
            session.scalars(
                select(MenuVersion).where(
                    MenuVersion.restaurant_id == tenant.restaurant_id,
                    MenuVersion.status == "PUBLISHED",
                )
            )
        )
        assert len(published) == 1
        active_branch_versions = list(
            session.scalars(
                select(Branch.active_menu_version_id).where(
                    Branch.restaurant_id == tenant.restaurant_id,
                    Branch.status == "ACTIVE",
                )
            )
        )
        assert active_branch_versions
        assert set(active_branch_versions) == {published[0].id}


def test_required_modifier_group_cannot_be_omitted(phase2):
    persisted_state(phase2, "modifier-required")
    _add_modifier_group(
        phase2,
        code="required-size",
        required=True,
        minimum=1,
        maximum=1,
        options=[("Synthetic Required Large", True)],
    )
    state = phase2.session_store.get("modifier-required")
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(session_key="modifier-required", state=state)
    assert error.value.code == "MODIFIER_REQUIRED"


def test_modifier_group_minimum_is_enforced(phase2):
    names = _add_modifier_group(
        phase2,
        code="minimum-two",
        minimum=2,
        maximum=2,
        options=[("Synthetic Min One", True), ("Synthetic Min Two", True)],
    )
    with pytest.raises(DomainError) as error:
        _confirm_with_options(phase2, "modifier-too-few", names[:1])
    assert error.value.code == "MODIFIER_TOO_FEW"


def test_modifier_group_maximum_is_enforced(phase2):
    names = _add_modifier_group(
        phase2,
        code="maximum-one",
        maximum=1,
        options=[("Synthetic Max One", True), ("Synthetic Max Two", True)],
    )
    with pytest.raises(DomainError) as error:
        _confirm_with_options(phase2, "modifier-too-many", names)
    assert error.value.code == "MODIFIER_TOO_MANY"


def test_inactive_modifier_option_is_rejected(phase2):
    names = _add_modifier_group(
        phase2,
        code="inactive-option",
        maximum=1,
        options=[("Synthetic Inactive Option", False)],
    )
    with pytest.raises(DomainError) as error:
        _confirm_with_options(phase2, "modifier-inactive", names)
    assert error.value.code == "MODIFIER_NOT_AVAILABLE"


def test_option_attached_to_another_item_is_rejected(phase2):
    names = _add_modifier_group(
        phase2,
        item_code="beef_rice",
        code="other-item-only",
        maximum=1,
        options=[("Synthetic Other Item Option", True)],
    )
    with pytest.raises(DomainError) as error:
        _confirm_with_options(phase2, "modifier-other-item", names)
    assert error.value.code == "MODIFIER_NOT_AVAILABLE"


def test_same_option_name_in_different_groups_is_ambiguous(phase2):
    for code in ["ambiguous-one", "ambiguous-two"]:
        _add_modifier_group(
            phase2,
            code=code,
            maximum=1,
            options=[("Synthetic Ambiguous Name", True)],
        )
    with pytest.raises(DomainError) as error:
        _confirm_with_options(phase2, "modifier-ambiguous", ["Synthetic Ambiguous Name"])
    assert error.value.code == "MODIFIER_AMBIGUOUS"


def test_same_authoritative_option_cannot_be_selected_twice(phase2):
    names = _add_modifier_group(
        phase2,
        code="duplicate-option",
        maximum=2,
        options=[("Synthetic Duplicate Option", True)],
    )
    with pytest.raises(DomainError) as error:
        _confirm_with_options(phase2, "modifier-duplicate", names * 2)
    assert error.value.code == "MODIFIER_DUPLICATE"
