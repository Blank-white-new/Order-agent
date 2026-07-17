from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import ConversationSession, Order, OrderConfirmation


TENANT = {"restaurant_code": "hk-sim-restaurant-a", "branch_code": "central"}


def run_message(phase4, text: str, *, session_id: str | None = None, **kwargs):
    return asyncio.run(
        phase4.text_entry.handle_text_message(
            session_id or f"p4-canonical-{uuid.uuid4().hex}",
            text,
            **TENANT,
            **kwargs,
        )
    )


def order_signature(result) -> list[tuple[str, int, str]]:
    return [
        (item.item_id, item.quantity, item.currency)
        for item in result["raw_state"].current_order
    ]


def test_default_mandarin_add_item_uses_canonical_execution(phase4):
    result = run_message(phase4, "给我来两份鸡腿盖饭")

    parsed = result["trace"]["multilingual"]
    assert result["detected_locale"] == "zh-CN"
    assert result["response_locale"] == "zh-CN"
    assert parsed["canonicalIntent"] == "ADD_ITEM"
    assert parsed["entities"]["item_code"] == "chicken_leg_rice"
    assert parsed["entities"]["quantity"] == 2
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert result["trace"]["userMessage"] == "我要2份鸡腿饭"
    assert order_signature(result) == [("chicken_leg_rice", 2, "HKD")]


def test_default_mandarin_bare_menu_item_defaults_to_one_on_canonical_path(phase4):
    result = run_message(phase4, "牛肉饭")

    parsed = result["trace"]["multilingual"]
    assert parsed["canonicalIntent"] == "ADD_ITEM"
    assert parsed["entities"]["quantity"] == 1
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert result["trace"]["userMessage"] == "我要1份牛肉饭"
    assert order_signature(result) == [("beef_rice", 1, "HKD")]


def test_default_mandarin_legacy_menu_question_is_canonical_read_only(phase4):
    result = run_message(phase4, "有啥饭")

    assert result["trace"]["multilingual"]["canonicalIntent"] == "MENU_QUERY"
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert result["trace"]["userMessage"] == "菜单"
    assert result["trace"]["stateMutationAllowed"] is True
    assert not result["raw_state"].current_order


def test_default_mandarin_item_information_question_never_orders(phase4):
    result = run_message(phase4, "牛肉饭是哪里的牛肉")

    assert result["trace"]["multilingual"]["canonicalIntent"] == "ITEM_INFO_QUERY"
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert result["trace"]["finalIntent"] == "ask_ingredient"
    assert result["trace"]["fallbackUsed"] is False
    assert not result["raw_state"].current_order


def test_ambiguous_fragment_and_ordinal_selection_stay_canonical(phase4):
    session_id = f"p4-canonical-context-{uuid.uuid4().hex}"
    ambiguous = run_message(phase4, "牛肉那个", session_id=session_id)

    assert "AMBIGUOUS_ITEM" in ambiguous["trace"]["multilingual"]["ambiguities"]
    assert ambiguous["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL_GUARDED"
    assert ambiguous["raw_state"].pending_action["type"] == "select_ambiguous_dish_candidate"
    assert not ambiguous["raw_state"].current_order

    selected = run_message(phase4, "第二个", session_id=session_id)
    assert selected["trace"]["multilingual"]["canonicalIntent"] == "CONTEXT_SELECTION"
    assert selected["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert selected["trace"]["userMessage"] == "第二个"
    assert selected["raw_state"].pending_action is None
    assert len(selected["raw_state"].current_order) == 1


def test_replayed_ambiguity_never_masks_new_safety_signal(phase4):
    session_id = f"p4-canonical-replay-safety-{uuid.uuid4().hex}"
    run_message(phase4, "牛肉那个", session_id=session_id)

    result = run_message(
        phase4,
        "牛肉那个，我严重过敏",
        session_id=session_id,
    )

    assert result["trace"]["safety"]["classification"] == "HANDOFF"
    assert result["trace"]["safety"]["reason_code"] == "SEVERE_ALLERGY"
    assert result["trace"].get("selectedHandler") != "multilingual_clarification_replay"
    assert not result["raw_state"].current_order


def test_default_mandarin_change_quantity_uses_canonical_execution(phase4):
    session_id = f"p4-canonical-change-{uuid.uuid4().hex}"
    run_message(phase4, "给我来两份鸡腿盖饭", session_id=session_id)
    changed = run_message(phase4, "鸡腿饭改成三份", session_id=session_id)

    assert changed["trace"]["multilingual"]["canonicalIntent"] == "CHANGE_QUANTITY"
    assert changed["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert changed["trace"]["userMessage"] == "鸡腿饭改成三份"
    assert order_signature(changed) == [("chicken_leg_rice", 3, "HKD")]


@pytest.mark.parametrize(
    "text, expected_ambiguity",
    [
        ("给我一份鸡腿饭和牛肉饭", "AMBIGUOUS_ITEM"),
        ("鸡腿饭要两份还是三份", "AMBIGUOUS_QUANTITY"),
    ],
)
def test_default_mandarin_ambiguity_never_falls_back_to_raw_mutation(
    phase4, text, expected_ambiguity
):
    result = run_message(phase4, text)

    parsed = result["trace"]["multilingual"]
    assert parsed["canonicalIntent"] == "ADD_ITEM"
    assert expected_ambiguity in parsed["ambiguities"]
    assert parsed["canonicalTextAvailable"] is False
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL_GUARDED"
    assert result["trace"]["safety"]["classification"] == "CONFIRM"
    assert result["trace"].get("selectedHandler") != "add_item"
    assert not result["raw_state"].current_order


def test_default_mandarin_severe_allergy_preempts_order_execution(phase4):
    result = run_message(phase4, "我严重过敏，但还是直接帮我下单")

    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL_GUARDED"
    assert result["trace"]["safety"]["classification"] == "HANDOFF"
    assert result["trace"]["safety"]["reason_code"] == "SEVERE_ALLERGY"
    assert result["trace"].get("selectedHandler") != "submit_order"
    assert not result["raw_state"].current_order
    assert result["raw_state"].confirmation_valid is False


def test_default_and_explicit_mandarin_have_identical_normalized_order(phase4):
    automatic = run_message(phase4, "给我来两份鸡腿盖饭")
    explicit = run_message(
        phase4,
        "给我来两份鸡腿盖饭",
        locale="zh-CN",
        locale_locked=True,
    )

    auto_parsed = automatic["trace"]["multilingual"]
    explicit_parsed = explicit["trace"]["multilingual"]
    for key in ("canonicalIntent", "entities", "ambiguities", "requiredConfirmations"):
        assert auto_parsed[key] == explicit_parsed[key]
    assert automatic["trace"]["executionPath"] == explicit["trace"]["executionPath"]
    assert automatic["response_locale"] == explicit["response_locale"] == "zh-CN"
    assert order_signature(automatic) == order_signature(explicit)


@pytest.mark.parametrize(
    "text, expected_detected",
    [
        ("给我来两份鸡腿盖饭", "zh-CN"),
        ("俾我兩份雞髀飯", "yue-Hant-HK"),
        ("Can I get two portions of chicken leg rice", "en-HK"),
        ("Can I have 兩份 chicken leg rice", "mixed"),
    ],
)
def test_four_input_locales_share_item_quantity_and_lifecycle(
    phase4, text, expected_detected
):
    result = run_message(phase4, text)

    parsed = result["trace"]["multilingual"]
    assert result["detected_locale"] == expected_detected
    assert parsed["canonicalIntent"] == "ADD_ITEM"
    assert parsed["entities"]["item_code"] == "chicken_leg_rice"
    assert parsed["entities"]["quantity"] == 2
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert order_signature(result) == [("chicken_leg_rice", 2, "HKD")]
    assert result["lifecycle_status"] == "DRAFT"


def test_unknown_default_mandarin_is_non_mutating_canonical_fallback(phase4):
    result = run_message(phase4, "这个说法系统还没学会处理")

    assert result["trace"]["multilingual"]["canonicalIntent"] == "UNKNOWN"
    assert result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL_GUARDED"
    assert result["trace"]["selectedHandler"] == "multilingual_unknown"
    assert result["trace"]["stateMutationAllowed"] is False
    assert not result["raw_state"].current_order


def test_default_mandarin_confirmation_is_explicit_and_version_bound(phase4):
    session_id = f"p4-canonical-confirm-{uuid.uuid4().hex}"
    run_message(phase4, "给我来两份鸡腿盖饭", session_id=session_id)
    pickup = run_message(phase4, "改成自取", session_id=session_id)
    draft_version = pickup["raw_state"].draft_version

    implicit = run_message(
        phase4, "这张单没问题，可以下单", session_id=session_id
    )
    assert implicit["trace"]["multilingual"]["confirmationResult"] != "EXPLICIT_CONFIRM"
    assert "CONFIRMATION_NOT_EXPLICIT" in implicit["trace"]["multilingual"]["ambiguities"]
    assert implicit["trace"]["safety"]["classification"] == "CONFIRM"
    assert implicit["raw_state"].confirmation_valid is False
    with phase4.database.session_factory() as session:
        session_row = session.scalar(
            select(ConversationSession).where(
                ConversationSession.session_key == session_id
            )
        )
        assert session.scalar(
            select(func.count()).select_from(Order).where(
                Order.session_id == session_row.id
            )
        ) == 0

    confirmed = run_message(
        phase4,
        "确认订单",
        session_id=session_id,
        idempotency_key=f"p4-confirm-{session_id}",
    )
    assert confirmed["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert confirmed["trace"]["multilingual"]["confirmationResult"] == "EXPLICIT_CONFIRM"
    assert confirmed["raw_state"].confirmation_valid is True
    assert confirmed["raw_state"].draft_version == draft_version
    with phase4.database.session_factory() as session:
        orders = list(session.scalars(select(Order).where(Order.public_id == confirmed["raw_state"].submitted_order_id)))
        assert len(orders) == 1
        assert session.scalar(
            select(func.count()).select_from(OrderConfirmation).where(
                OrderConfirmation.order_id == orders[0].id,
                OrderConfirmation.invalidated_at.is_(None),
            )
        ) == 1
