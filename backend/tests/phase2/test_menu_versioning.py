from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Branch,
    MenuCategory,
    MenuCategoryTranslation,
    MenuItem,
    MenuItemAlias,
    MenuItemTranslation,
    MenuVersion,
)
from app.domain.errors import DomainError
from app.services.menu_management_service import MenuManagementService
from app.services.menu_service import MenuService
from .helpers import persisted_state


def _new_menu(context, *, price_minor: int = 3300, name: str = "Synthetic New Chicken") -> tuple[int, int]:
    tenant = context.tenant_service.resolve("hk-sim-restaurant-a", "central")
    with context.uow_factory() as uow:
        version = MenuVersion(
            restaurant_id=tenant.restaurant_id,
            version_number=uow.menus.next_version_number(tenant.restaurant_id),
            status="DRAFT",
        )
        uow.menus.add(version)
        uow.flush()
        category = MenuCategory(menu_version_id=version.id, code="mains", sort_order=0, active=True)
        uow.menus.add(category)
        uow.flush()
        uow.menus.add(MenuCategoryTranslation(category_id=category.id, locale="zh-CN", name="Synthetic Mains"))
        item = MenuItem(
            menu_version_id=version.id,
            category_id=category.id,
            code="chicken_leg_rice",
            base_price_minor=price_minor,
            currency="HKD",
            active=True,
        )
        uow.menus.add(item)
        uow.flush()
        uow.menus.add(MenuItemTranslation(menu_item_id=item.id, locale="zh-CN", name=name, description="synthetic"))
        uow.menus.add(
            MenuItemAlias(
                menu_item_id=item.id,
                menu_version_id=version.id,
                locale="zh-CN",
                alias="new chicken alias",
                normalized_alias="newchickenalias",
            )
        )
        return version.id, item.id


def test_publish_is_transactional_archives_old_and_updates_all_restaurant_branches(phase2):
    tenant = phase2.tenant_service.resolve("hk-sim-restaurant-a", "central")
    service = MenuManagementService(phase2.uow_factory)
    cached_menu = MenuService(database=phase2.database)
    old_price = cached_menu.get_item_price_minor("鸡腿饭")
    version_id, _ = _new_menu(phase2)
    published = service.publish(tenant.restaurant_id, version_id)
    assert published.status == "PUBLISHED"
    with phase2.database.session_factory() as session:
        versions = list(session.scalars(select(MenuVersion).where(MenuVersion.restaurant_id == tenant.restaurant_id)))
        assert [version.status for version in versions].count("PUBLISHED") == 1
        assert all(branch.active_menu_version_id == version_id for branch in session.scalars(select(Branch).where(Branch.restaurant_id == tenant.restaurant_id)))
    cached_menu.refresh()
    assert old_price == 2600
    assert cached_menu.get_item_price_minor("Synthetic New Chicken") == 3300


def test_published_menu_is_immutable_through_management_service(phase2):
    tenant = phase2.tenant_service.resolve()
    with phase2.uow_factory() as uow:
        published = uow.menus.get_active_version(tenant.branch_id)
        published_id = published.id
    with pytest.raises(DomainError) as error:
        MenuManagementService(phase2.uow_factory).assert_mutable(published_id)
    assert error.value.code == "PUBLISHED_MENU_IMMUTABLE"


def test_cross_version_category_reference_is_rejected_by_database(phase2):
    tenant = phase2.tenant_service.resolve()
    with phase2.database.session_factory() as session:
        old_category = session.scalar(
            select(MenuCategory).join(MenuVersion).where(MenuVersion.restaurant_id == tenant.restaurant_id)
        )
        version = MenuVersion(restaurant_id=tenant.restaurant_id, version_number=99, status="DRAFT")
        session.add(version)
        session.flush()
        session.add(
            MenuItem(
                menu_version_id=version.id,
                category_id=old_category.id,
                code="invalid-cross-version",
                base_price_minor=100,
                currency="HKD",
                active=True,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_historical_order_keeps_old_name_price_and_menu_version(phase2):
    state = persisted_state(phase2, "snapshot-order")
    confirmed = phase2.order_service.confirm_order(session_key="snapshot-order", state=state, idempotency_key="snapshot")
    with phase2.uow_factory() as uow:
        tenant = phase2.tenant_service.resolve()
        order = uow.orders.get_by_public_id(confirmed.public_id, tenant.restaurant_id, tenant.branch_id)
        before = uow.orders.list_items(order.id)[0]
        before_snapshot = (before.item_name_snapshot, before.unit_price_minor, before.menu_version_id)

    version_id, _ = _new_menu(phase2, price_minor=9100, name="Synthetic Renamed Chicken")
    tenant = phase2.tenant_service.resolve()
    MenuManagementService(phase2.uow_factory).publish(tenant.restaurant_id, version_id)

    with phase2.uow_factory() as uow:
        order = uow.orders.get_by_public_id(confirmed.public_id, tenant.restaurant_id, tenant.branch_id)
        after = uow.orders.list_items(order.id)[0]
        assert (after.item_name_snapshot, after.unit_price_minor, after.menu_version_id) == before_snapshot
        assert before_snapshot[0] == "鸡腿饭"
        assert before_snapshot[1] == 2600


def test_alias_uniqueness_is_scoped_to_menu_version(phase2):
    version_id, new_item_id = _new_menu(phase2)
    with phase2.database.session_factory() as session:
        old_alias = session.scalar(select(MenuItemAlias))
        session.add(
            MenuItemAlias(
                menu_item_id=new_item_id,
                menu_version_id=version_id,
                locale=old_alias.locale,
                alias=old_alias.alias,
                normalized_alias=old_alias.normalized_alias,
            )
        )
        session.commit()
