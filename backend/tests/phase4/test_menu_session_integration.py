from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import (
    Branch,
    ConversationSession,
    MenuItem,
    MenuItemAlias,
    MenuItemTranslation,
    MenuVersion,
    ModifierGroupTranslation,
    ModifierOptionTranslation,
)
from app.services.phase4_menu_seed_service import Phase4MenuSeedService


def test_phase4_seed_publishes_versioned_complete_catalog(phase4):
    summary = phase4.seed_summary
    assert summary.restaurants == 2
    assert summary.menu_versions_created == 2
    assert summary.items == 22
    assert summary.aliases >= 66
    with phase4.uow_factory() as uow:
        published = uow.session.scalars(
            select(MenuVersion).where(MenuVersion.status == "PUBLISHED")
        ).all()
        archived = uow.session.scalars(
            select(MenuVersion).where(MenuVersion.status == "ARCHIVED")
        ).all()
        branches = uow.session.scalars(select(Branch).where(Branch.status == "ACTIVE")).all()
        assert len(published) == 2
        assert len(archived) == 2
        assert all(branch.active_menu_version_id in {version.id for version in published} for branch in branches)


def test_phase4_seed_is_idempotent(phase4):
    before = None
    with phase4.uow_factory() as uow:
        before = uow.session.scalar(select(func.count()).select_from(MenuVersion))
    repeat = Phase4MenuSeedService(phase4.uow_factory).seed()
    with phase4.uow_factory() as uow:
        after = uow.session.scalar(select(func.count()).select_from(MenuVersion))
    assert repeat.menu_versions_created == 0
    assert repeat.idempotent_restaurants == 2
    assert before == after


def test_every_active_item_has_three_names_and_aliases(phase4):
    with phase4.uow_factory() as uow:
        published_ids = set(
            uow.session.scalars(
                select(MenuVersion.id).where(MenuVersion.status == "PUBLISHED")
            ).all()
        )
        items = uow.session.scalars(
            select(MenuItem).where(MenuItem.menu_version_id.in_(published_ids), MenuItem.active.is_(True))
        ).all()
        assert len(items) == 22
        for item in items:
            locales = set(
                uow.session.scalars(
                    select(MenuItemTranslation.locale).where(MenuItemTranslation.menu_item_id == item.id)
                ).all()
            )
            alias_locales = set(
                uow.session.scalars(
                    select(MenuItemAlias.locale).where(MenuItemAlias.menu_item_id == item.id)
                ).all()
            )
            assert locales == {"zh-CN", "yue-Hant-HK", "en-HK"}
            assert alias_locales == locales


def test_modifier_translations_are_version_scoped_and_complete(phase4):
    with phase4.uow_factory() as uow:
        group_rows = uow.session.scalars(select(ModifierGroupTranslation)).all()
        option_rows = uow.session.scalars(select(ModifierOptionTranslation)).all()
        assert group_rows and option_rows
        by_group = {}
        for row in group_rows:
            by_group.setdefault((row.menu_version_id, row.modifier_group_id), set()).add(row.locale)
        by_option = {}
        for row in option_rows:
            by_option.setdefault((row.menu_version_id, row.modifier_option_id), set()).add(row.locale)
        assert all(locales == {"zh-CN", "yue-Hant-HK", "en-HK"} for locales in by_group.values())
        assert all(locales == {"zh-CN", "yue-Hant-HK", "en-HK"} for locales in by_option.values())


def test_archived_menu_rows_remain_unchanged_and_distinct(phase4):
    with phase4.uow_factory() as uow:
        archived_ids = set(uow.session.scalars(select(MenuVersion.id).where(MenuVersion.status == "ARCHIVED")).all())
        published_ids = set(uow.session.scalars(select(MenuVersion.id).where(MenuVersion.status == "PUBLISHED")).all())
        archived_items = uow.session.scalars(select(MenuItem).where(MenuItem.menu_version_id.in_(archived_ids))).all()
        published_items = uow.session.scalars(select(MenuItem).where(MenuItem.menu_version_id.in_(published_ids))).all()
        assert archived_items and published_items
        assert {item.id for item in archived_items}.isdisjoint({item.id for item in published_items})
        assert all(item.code for item in archived_items)
        assert uow.session.scalar(
            select(func.count()).select_from(MenuItemTranslation).where(
                MenuItemTranslation.menu_item_id.in_({item.id for item in archived_items})
            )
        ) > 0


def test_language_switch_persists_without_clearing_order_or_changing_version(phase4):
    session_id = f"p4-switch-{uuid.uuid4().hex}"
    added = asyncio.run(phase4.text_entry.handle_text_message(
        session_id,
        "I want two portions of chicken leg rice",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
        locale_hint="en-HK",
    ))
    assert len(added["raw_state"].current_order) == 1
    version = added["raw_state"].draft_version
    switched = asyncio.run(phase4.text_entry.handle_text_message(
        session_id,
        "轉做廣東話",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    ))
    assert switched["response_locale"] == "yue-Hant-HK"
    assert switched["raw_state"].locale_locked
    assert len(switched["raw_state"].current_order) == 1
    assert switched["raw_state"].draft_version == version
    restored = phase4.store.get(session_id, "hk-sim-restaurant-a", "central")
    assert restored.response_locale == "yue-Hant-HK"
    assert restored.locale_locked


def test_sessions_and_tenants_do_not_share_locale_or_menu_state(phase4):
    one = f"p4-one-{uuid.uuid4().hex}"
    two = f"p4-two-{uuid.uuid4().hex}"
    asyncio.run(phase4.text_entry.handle_text_message(
        one, "English please", restaurant_code="hk-sim-restaurant-a", branch_code="central"
    ))
    state_one = phase4.store.get(one, "hk-sim-restaurant-a", "central")
    state_two = phase4.store.get(two, "hk-sim-restaurant-b", "harbor")
    assert state_one.response_locale == "en-HK"
    assert state_two.response_locale == "zh-CN"
    assert not state_two.current_order


def test_unsupported_language_enters_handoff_without_mutation(phase4):
    result = asyncio.run(phase4.text_entry.handle_text_message(
        f"p4-und-{uuid.uuid4().hex}",
        "日本語でお願いします",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    ))
    assert result["trace"]["safety"]["classification"] == "HANDOFF"
    assert result["trace"]["safety"]["reason_code"] == "LANGUAGE_UNSUPPORTED"
    assert not result["raw_state"].current_order


def test_language_switch_does_not_release_existing_safety_hold(phase4):
    session_id = f"p4-hold-{uuid.uuid4().hex}"
    held = asyncio.run(phase4.text_entry.handle_text_message(
        session_id,
        "I have a severe allergy and risk of anaphylaxis",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    ))
    handoff_id = held["raw_state"].handoff_public_id
    switched = asyncio.run(phase4.text_entry.handle_text_message(
        session_id,
        "請說普通話",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    ))
    assert switched["raw_state"].handoff_public_id == handoff_id
    assert switched["raw_state"].safety_reason_code == "SEVERE_ALLERGY"
    assert switched["raw_state"].handoff_status != "NOT_REQUIRED"


def test_language_switch_cannot_mask_new_safety_signal(phase4):
    result = asyncio.run(phase4.text_entry.handle_text_message(
        f"p4-switch-risk-{uuid.uuid4().hex}",
        "English please, I have a severe allergy and risk of anaphylaxis",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    ))
    assert result["response_locale"] == "en-HK"
    assert result["trace"]["safety"]["classification"] == "HANDOFF"
    assert result["trace"]["safety"]["reason_code"] == "SEVERE_ALLERGY"
    assert not result["raw_state"].current_order


def test_session_row_persists_concrete_response_locale(phase4):
    with phase4.uow_factory() as uow:
        rows = uow.session.scalars(select(ConversationSession)).all()
        assert rows
        assert all(row.locale in {"zh-CN", "yue-Hant-HK", "en-HK"} for row in rows)
