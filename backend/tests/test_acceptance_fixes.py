"""Acceptance test scenarios A-G: real multi-turn conversation verification.

These tests check full state after each turn, not just intent.
They were added as part of the real-conversation acceptance fix round.
"""
from app.state.session_state import SessionState
from app.agents.orchestrator import OrchestratorAgent


# ═══════════════════════════════════════════════════════════════════════
# Scenario A: cancel → reorder → confirm
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_a_cancel_reorder_confirm_state():
    """After cancel→reorder, confirm should NOT clear order (Scenario A)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Turn 1: order beef rice
    r1 = orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "牛肉饭"
    assert state.current_order[0].quantity == 1
    assert "牛肉饭" in r1["response"]
    assert r1["trace"]["fallbackUsed"] is False

    # Turn 2: cancel (sets confirm_clear_order pending)
    r2 = orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"
    # Order should NOT be cleared yet (pending confirmation)
    assert len(state.current_order) == 1
    assert r2["trace"]["fallbackUsed"] is False

    # Turn 3: reorder chicken rice
    # With confirm_clear_order pending, this should clear old order and start fresh
    r3 = orchestrator.handle_user_message("鸡腿饭", state)
    assert state.pending_action is None, "pending_action must be cleared after reorder"
    assert len(state.current_order) == 1, "old order cleared, only new item remains"
    assert state.current_order[0].name == "鸡腿饭", "only chicken rice should remain"
    assert "牛肉饭" not in [item.name for item in state.current_order], "beef rice must be gone"
    assert r3["trace"]["fallbackUsed"] is False
    assert "重新开始点餐" in r3["response"] or "鸡腿饭" in r3["response"]

    # Turn 4: confirm — must NOT trigger old confirm_clear_order
    r4 = orchestrator.handle_user_message("确认", state)
    assert state.pending_action is None, "no stale pending_action after confirm"
    assert len(state.current_order) == 1, "order must not be cleared"
    assert state.current_order[0].name == "鸡腿饭"
    assert state.submitted is False, "should not submit without address/phone"
    assert r4["trace"]["fallbackUsed"] is False
    # Should ask for delivery/pickup or address
    assert "地址" in r4["response"] or "配送" in r4["response"] or "自取" in r4["response"]


def test_scenario_a_no_stale_confirm_clear_order():
    """Confirm_clear_order must not persist after new order_food."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # Reorder through order_food
    orchestrator.handle_user_message("鸡腿饭", state)
    assert state.pending_action is None

    # order_food with another item to test quantity too
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    orchestrator.handle_user_message("可乐", state)
    assert state.pending_action is None, "order_food should clear confirm_clear_order"


# ═══════════════════════════════════════════════════════════════════════
# Scenario B: normal clear still works
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_b_normal_clear_flow():
    """Cancel→confirm should clear order normally (Scenario B)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Turn 1: order
    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    # Turn 2: cancel
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    # Turn 3: confirm clear
    r3 = orchestrator.handle_user_message("确认", state)
    assert len(state.current_order) == 0, "order should be cleared"
    assert state.pending_action is None, "pending_action should be cleared"
    assert state.submitted is False, "should not submit empty order"
    assert state.stage == "ordering", "should return to ordering stage"
    assert r3["trace"]["fallbackUsed"] is False
    assert "清空" in r3["response"] or "空" in r3["response"]


def test_scenario_b_can_reorder_after_clear():
    """After clear, user should be able to reorder normally."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    orchestrator.handle_user_message("确认", state)
    assert len(state.current_order) == 0

    # Now reorder should work
    r = orchestrator.handle_user_message("鸡腿饭", state)
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert r["trace"]["fallbackUsed"] is False


# ═══════════════════════════════════════════════════════════════════════
# Scenario C: menu context then "黑椒那个"
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_c_black_pepper_after_menu():
    """After viewing menu, '黑椒那个' should order 黑椒牛肉饭 (Scenario C)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Turn 1: view rice menu
    r1 = orchestrator.handle_user_message("有啥饭", state)
    assert r1["trace"]["fallbackUsed"] is False
    assert state.viewed_category is not None

    # Turn 2: "黑椒那个" → should uniquely match 黑椒牛肉饭
    r2 = orchestrator.handle_user_message("黑椒那个", state)
    assert r2["trace"]["fallbackUsed"] is False, "'黑椒那个' must not fallback"
    assert r2["trace"]["finalIntent"] == "order_food", (
        f"Expected order_food, got {r2['trace']['finalIntent']}"
    )
    assert len(state.current_order) == 1, "order should have 1 item"
    assert state.current_order[0].name == "黑椒牛肉饭", (
        f"Expected 黑椒牛肉饭, got {state.current_order[0].name}"
    )
    assert state.current_order[0].quantity == 1
    assert "黑椒牛肉饭" in r2["response"]


def test_scenario_c_black_pepper_unique_match():
    """'黑椒那个' should NOT match 牛肉饭 — it must match 黑椒牛肉饭."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    orchestrator.handle_user_message("黑椒那个", state)

    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭", (
        f"Must match 黑椒牛肉饭, not {state.current_order[0].name}"
    )
    assert "牛肉饭" != state.current_order[0].name, "Must NOT be plain 牛肉饭"


# ═══════════════════════════════════════════════════════════════════════
# Scenario D: menu context then "鸡腿那个"
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_d_chicken_leg_after_menu():
    """After viewing menu, '鸡腿那个' should order 鸡腿饭 (Scenario D)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Turn 1: view rice menu
    r1 = orchestrator.handle_user_message("有啥饭", state)
    assert r1["trace"]["fallbackUsed"] is False

    # Turn 2: "鸡腿那个" → should uniquely match 鸡腿饭
    r2 = orchestrator.handle_user_message("鸡腿那个", state)
    assert r2["trace"]["fallbackUsed"] is False, "'鸡腿那个' must not fallback"
    assert r2["trace"]["finalIntent"] == "order_food", (
        f"Expected order_food, got {r2['trace']['finalIntent']}"
    )
    assert len(state.current_order) == 1, "order should have 1 item"
    assert state.current_order[0].name == "鸡腿饭", (
        f"Expected 鸡腿饭, got {state.current_order[0].name}"
    )
    assert state.current_order[0].quantity == 1
    assert "鸡腿饭" in r2["response"]


def test_scenario_d_chicken_leg_unique_match():
    """'鸡腿那个' must not match another rice dish."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    orchestrator.handle_user_message("鸡腿那个", state)

    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    # Should NOT be 宫保鸡丁饭 (which also contains 鸡)
    assert state.current_order[0].name != "宫保鸡丁饭"


# ═══════════════════════════════════════════════════════════════════════
# Scenario E: bare "那个" must not default to first item
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_e_bare_nage_no_order():
    """Bare '那个' without dish fragment must NOT order anything (Scenario E)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # View menu first
    orchestrator.handle_user_message("有啥饭", state)

    # "那个" alone — no dish fragment, should not order
    r2 = orchestrator.handle_user_message("那个", state)
    assert len(state.current_order) == 0, (
        f"Bare '那个' must not add items, got {[(e.name, e.quantity) for e in state.current_order]}"
    )
    # Should either fallback (asking for clarification) or give guidance
    # Must NOT be an order mutation intent
    if r2["trace"]["finalIntent"] != "fallback":
        assert r2["trace"]["finalIntent"] != "order_food", (
            "Bare '那个' must not be treated as order_food"
        )
        assert r2["trace"]["finalIntent"] != "select_recommendation", (
            "Bare '那个' must not be treated as select_recommendation"
        )


def test_scenario_e_bare_nage_with_recommendations():
    """Even with recommendations, bare '那个' must not auto-select first."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Get recommendations
    orchestrator.handle_user_message("推荐", state)
    assert len(state.last_recommendations) > 0

    # "那个" alone should not auto-select recommendation index 0
    r2 = orchestrator.handle_user_message("那个", state)
    assert len(state.current_order) == 0, (
        f"Bare '那个' with recommendations must not auto-select, "
        f"got {[(e.name, e.quantity) for e in state.current_order]}"
    )


def test_scenario_e_explicit_index_still_works():
    """'第一个' should still work for selecting recommendations."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("推荐", state)
    assert len(state.last_recommendations) > 0

    r2 = orchestrator.handle_user_message("第一个", state)
    assert r2["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1, "Explicit '第一个' should select recommendation"


# ═══════════════════════════════════════════════════════════════════════
# Scenario F: Chinese number quantity parsing (full chain)
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_f_six_chicken_leg():
    """'六个鸡腿饭' should produce order with quantity 6."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    r = orchestrator.handle_user_message("六个鸡腿饭", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert state.current_order[0].quantity == 6, (
        f"Expected quantity 6, got {state.current_order[0].quantity}"
    )


def test_scenario_f_seven_cola():
    """'七瓶可乐' should produce order with quantity 7."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    r = orchestrator.handle_user_message("七瓶可乐", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "可乐"
    assert state.current_order[0].quantity == 7


def test_scenario_f_eight_beef_rice():
    """'八份牛肉饭' should produce order with quantity 8."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    r = orchestrator.handle_user_message("八份牛肉饭", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "牛肉饭"
    assert state.current_order[0].quantity == 8


def test_scenario_f_nine_black_pepper():
    """'九份黑椒牛肉饭' should produce order with quantity 9."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    r = orchestrator.handle_user_message("九份黑椒牛肉饭", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"
    assert state.current_order[0].quantity == 9


def test_scenario_f_ten_chicken_leg():
    """'十份鸡腿饭' should produce order with quantity 10."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    r = orchestrator.handle_user_message("十份鸡腿饭", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert state.current_order[0].quantity == 10


def test_scenario_f_chinese_numbers_dont_duplicate():
    """Chinese number orders should not create duplicate line items."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Order same item twice with Chinese numbers
    orchestrator.handle_user_message("三个鸡腿饭", state)
    orchestrator.handle_user_message("两个鸡腿饭", state)

    # Should have ONE line item with quantity 5, not two line items
    assert len(state.current_order) == 1, (
        f"Should merge same item, got {len(state.current_order)} line items"
    )
    assert state.current_order[0].quantity == 5, (
        f"Expected total quantity 5, got {state.current_order[0].quantity}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Scenario G: rollback clears pending_action
# ═══════════════════════════════════════════════════════════════════════

def test_scenario_g_rollback_clears_pending_action_full_chain():
    """After rollback, confirm must NOT trigger old pending (Scenario G)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Turn 1: order
    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    # Turn 2: cancel (sets confirm_clear_order)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    # Turn 3: "我只是问一下" triggers rollback
    r3 = orchestrator.handle_user_message("我只是问一下", state)
    assert state.pending_action is None, (
        f"Rollback must clear pending_action, got {state.pending_action}"
    )
    assert len(state.current_order) == 0, "Rollback should restore empty order"
    assert r3["trace"]["rollbackApplied"] is True

    # Turn 4: confirm — must NOT trigger old clear (order already empty)
    r4 = orchestrator.handle_user_message("确认", state)
    assert state.pending_action is None
    assert state.submitted is False, "should not submit empty order"
    # Should not say "已清空" — the order was already empty
    assert "清空" not in r4["response"], (
        f"Should not say order cleared when it was already empty: {r4['response']}"
    )


def test_scenario_g_rollback_with_multiple_triggers():
    """Multiple rollback triggers should all clear pending_action."""
    orchestrator = OrchestratorAgent()

    triggers = [
        "我没点",
        "不是这个",
        "我只是问一下",
        "没让你加",
        "加错了",
    ]

    for trigger in triggers:
        state = SessionState()
        orchestrator.handle_user_message("牛肉饭", state)
        orchestrator.handle_user_message("不要了", state)
        assert state.pending_action is not None

        orchestrator.handle_user_message(trigger, state)
        assert state.pending_action is None, (
            f"Rollback trigger '{trigger}' must clear pending_action"
        )


def test_scenario_g_rollback_confirmation_safety():
    """After rollback+cleared pending, confirmation is safe."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)

    # Multiple rollback-like messages
    orchestrator.handle_user_message("弄错了", state)
    assert state.pending_action is None

    # Confirming should not do anything dangerous
    r = orchestrator.handle_user_message("确认", state)
    assert state.submitted is False
    assert len(state.current_order) == 0


# ═══════════════════════════════════════════════════════════════════════
# Cross-scenario regression: pending_action clearing consistency
# ═══════════════════════════════════════════════════════════════════════

def test_order_multiple_items_clears_confirm_clear_order():
    """_order_multiple_items should clear stale confirm_clear_order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # order_multiple_items should clear the pending
    orchestrator.handle_user_message("鸡腿饭 可乐", state)
    assert state.pending_action is None, (
        "order_multiple_items must clear confirm_clear_order"
    )


def test_select_recommendation_clears_confirm_clear_order():
    """_select_recommendation should clear stale confirm_clear_order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # Set up recommendations, then select
    orchestrator.handle_user_message("推荐", state)
    # Clear recommendations reset? No — but we need an active recommendation context
    # The cancel pending should be cleared when a new selection is made
    # Re-create state with pending then select recommendation
    state2 = SessionState()
    orchestrator.handle_user_message("牛肉饭", state2)
    orchestrator.handle_user_message("不要了", state2)
    assert state2.pending_action is not None

    # Get recommendations and select first
    r = orchestrator.handle_user_message("推荐", state2)
    assert len(state2.last_recommendations) > 0

    r2 = orchestrator.handle_user_message("第一个", state2)
    assert state2.pending_action is None, (
        "select_recommendation must clear confirm_clear_order"
    )
    assert r2["trace"]["fallbackUsed"] is False


def test_replace_item_clears_confirm_clear_order():
    """_replace_item should clear stale confirm_clear_order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # Replace item should clear pending
    orchestrator.handle_user_message("把牛肉饭换成鸡腿饭", state)
    assert state.pending_action is None, (
        "replace_item must clear confirm_clear_order"
    )
    # Order should have the replacement
    names = [item.name for item in state.current_order]
    assert "鸡腿饭" in names
    assert "牛肉饭" not in names


def test_update_quantity_clears_confirm_clear_order():
    """_update_item_quantity should clear stale confirm_clear_order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # Update quantity should clear pending if it matches
    # Need to use a phrase that triggers update_item_quantity
    r = orchestrator.handle_user_message("牛肉饭改成三份", state)
    assert state.pending_action is None, (
        "update_item_quantity must clear confirm_clear_order"
    )


# ═══════════════════════════════════════════════════════════════════════
# Round 3 — P1: Cancel-then-reorder clears old order
# ═══════════════════════════════════════════════════════════════════════

def test_p1_cancel_reorder_only_new_item_remains():
    """牛肉饭→不要了→鸡腿饭: only 鸡腿饭 remains, 牛肉饭 cleared."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    r = orchestrator.handle_user_message("鸡腿饭", state)
    assert state.pending_action is None
    assert len(state.current_order) == 1, (
        f"Expected 1 item, got {len(state.current_order)}: "
        f"{[(e.name, e.quantity) for e in state.current_order]}"
    )
    assert state.current_order[0].name == "鸡腿饭"
    assert "牛肉饭" not in [e.name for e in state.current_order]
    assert r["trace"]["fallbackUsed"] is False


def test_p1_cancel_reorder_confirm_does_not_clear():
    """牛肉饭→不要了→鸡腿饭→确认: new order not cleared, not submitted."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    orchestrator.handle_user_message("鸡腿饭", state)
    r = orchestrator.handle_user_message("确认", state)

    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert state.submitted is False
    assert "地址" in r["response"] or "配送" in r["response"] or "自取" in r["response"]


def test_p1_cancel_reorder_with_multiple_items():
    """牛肉饭→不要了→鸡腿饭 可乐: old cleared, both new items remain."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    orchestrator.handle_user_message("鸡腿饭 可乐", state)

    assert state.pending_action is None
    names = [e.name for e in state.current_order]
    assert "鸡腿饭" in names
    assert "可乐" in names
    assert "牛肉饭" not in names


def test_p1_cancel_reorder_via_recommendation():
    """牛肉饭→不要了→推荐→第一个: recommendation question expires old clear pending."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    orchestrator.handle_user_message("推荐", state)
    assert len(state.last_recommendations) > 0

    r = orchestrator.handle_user_message("第一个", state)
    assert state.pending_action is None
    assert len(state.current_order) == 2
    assert "牛肉饭" in [e.name for e in state.current_order]
    assert r["trace"]["fallbackUsed"] is False


def test_p1_normal_append_still_preserves_both():
    """牛肉饭→鸡腿饭: both items preserved (no cancel between them)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("鸡腿饭", state)

    assert len(state.current_order) == 2
    names = [e.name for e in state.current_order]
    assert "牛肉饭" in names
    assert "鸡腿饭" in names


def test_p1_normal_clear_still_works():
    """牛肉饭→不要了→确认: order cleared, pending None."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    r = orchestrator.handle_user_message("确认", state)

    assert len(state.current_order) == 0
    assert state.pending_action is None
    assert state.submitted is False
    assert state.stage == "ordering"


# ═══════════════════════════════════════════════════════════════════════
# Round 3 — P2: Ambiguous dish fragment candidates
# ═══════════════════════════════════════════════════════════════════════

def test_p2_ambiguous_fragment_lists_candidates():
    """牛肉那个: lists 牛肉饭, 黑椒牛肉饭, 牛肉面, does NOT order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    r = orchestrator.handle_user_message("牛肉那个", state)

    assert len(state.current_order) == 0, (
        f"Must not order on ambiguous fragment, got {[(e.name, e.quantity) for e in state.current_order]}"
    )
    # Response should mention multiple candidates
    response = r["response"]
    candidates_mentioned = sum(
        1 for name in ["牛肉饭", "黑椒牛肉饭", "牛肉面"] if name in response
    )
    assert candidates_mentioned >= 2, (
        f"Response must list >=2 candidates, got: {response}"
    )
    assert r["trace"]["fallbackUsed"] is False


def test_p2_unique_fragment_still_orders():
    """黑椒那个: uniquely matches 黑椒牛肉饭, adds to order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    r = orchestrator.handle_user_message("黑椒那个", state)

    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"
    assert r["trace"]["fallbackUsed"] is False


def test_p2_chicken_leg_fragment_still_orders():
    """鸡腿那个: uniquely matches 鸡腿饭, adds to order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    r = orchestrator.handle_user_message("鸡腿那个", state)

    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert r["trace"]["fallbackUsed"] is False


def test_p2_bare_nage_still_does_not_order():
    """那个 alone: no dish fragment, does NOT order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    r = orchestrator.handle_user_message("那个", state)

    assert len(state.current_order) == 0, (
        f"Bare 那个 must not add items"
    )
    if r["trace"]["finalIntent"] != "fallback":
        assert r["trace"]["finalIntent"] != "order_food"


# ═══════════════════════════════════════════════════════════════════════
# Round 3 — P3: 就那个/要那个/来那个 ask for clarity
# ═══════════════════════════════════════════════════════════════════════

def test_p3_jiu_nage_with_recommendations_asks_which():
    """推荐→就那个: asks which one, does NOT order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("推荐", state)
    assert len(state.last_recommendations) > 0

    r = orchestrator.handle_user_message("就那个", state)
    assert len(state.current_order) == 0, "Must not order on 就那个"
    assert "第几个" in r["response"] or "第一个" in r["response"], (
        f"Response should ask which number, got: {r['response']}"
    )
    assert r["trace"]["fallbackUsed"] is False


def test_p3_yao_nage_with_menu_asks_which():
    """有啥饭→要那个: asks which one, does NOT order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    r = orchestrator.handle_user_message("要那个", state)

    assert len(state.current_order) == 0, "Must not order on 要那个"
    assert "第几个" in r["response"] or "菜名" in r["response"] or "第一个" in r["response"], (
        f"Response should ask for clarification, got: {r['response']}"
    )
    assert r["trace"]["fallbackUsed"] is False


def test_p3_lai_nage_with_menu_asks_which():
    """有啥饭→来那个: asks which one, does NOT order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥饭", state)
    r = orchestrator.handle_user_message("来那个", state)

    assert len(state.current_order) == 0
    assert "第几个" in r["response"] or "菜名" in r["response"] or "第一个" in r["response"]


def test_p3_explicit_first_still_orders():
    """推荐→第一个: still selects first recommendation."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("推荐", state)
    r = orchestrator.handle_user_message("第一个", state)

    assert len(state.current_order) == 1
    assert r["trace"]["finalIntent"] == "select_recommendation"
    assert r["trace"]["fallbackUsed"] is False


# ═══════════════════════════════════════════════════════════════════════
# Round 4 — P1: Ambiguous candidate pending + selection
# ═══════════════════════════════════════════════════════════════════════

def test_ambiguous_select_by_ordinal_second():
    """牛肉那个→第二个: selects candidate[1] (黑椒牛肉饭)."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "select_ambiguous_dish_candidate"
    candidates = state.pending_action.get("candidates", [])
    assert len(candidates) >= 2

    r = orchestrator.handle_user_message("第二个", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == candidates[1]["name"]
    assert state.pending_action is None


def test_ambiguous_select_by_number_2():
    """牛肉那个→2: numeric index selects candidate[1]."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    assert state.pending_action is not None

    r = orchestrator.handle_user_message("2", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    # candidate[1] should be 黑椒牛肉饭
    assert state.pending_action is None


def test_ambiguous_select_by_name():
    """牛肉那个→黑椒牛肉饭: selects by exact candidate name."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    assert state.pending_action is not None

    r = orchestrator.handle_user_message("黑椒牛肉饭", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"
    assert state.pending_action is None


def test_ambiguous_select_by_fragment():
    """牛肉那个→黑椒那个: unique fragment match within candidates."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    assert state.pending_action is not None

    r = orchestrator.handle_user_message("黑椒那个", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"
    assert state.pending_action is None


def test_ambiguous_cancel_clears_pending_only():
    """牛肉那个→算了: clears candidate pending, does NOT clear existing order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add an item to the order first
    orchestrator.handle_user_message("可乐", state)
    assert len(state.current_order) == 1

    # Trigger ambiguous candidates
    orchestrator.handle_user_message("牛肉那个", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "select_ambiguous_dish_candidate"

    # Cancel the candidate selection
    r = orchestrator.handle_user_message("算了", state)
    assert state.pending_action is None, "Candidate pending must be cleared"
    assert len(state.current_order) == 1, "Existing order must not be cleared"
    assert state.current_order[0].name == "可乐", "可乐 must remain"


def test_ambiguous_select_by_index_first():
    """牛肉那个→第一个: selects candidate[0]."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    candidates = state.pending_action.get("candidates", [])

    r = orchestrator.handle_user_message("第一个", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == candidates[0]["name"]
    assert state.pending_action is None


def test_ambiguous_select_by_index_third():
    """牛肉那个→第三个: selects candidate[2]."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    candidates = state.pending_action.get("candidates", [])
    assert len(candidates) >= 3

    r = orchestrator.handle_user_message("第三个", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    assert state.current_order[0].name == candidates[2]["name"]
    assert state.pending_action is None


def test_ambiguous_priority_over_recommendations():
    """推荐→牛肉那个→第二个: selects from candidates, not recommendations."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("推荐", state)
    assert len(state.last_recommendations) > 0

    orchestrator.handle_user_message("牛肉那个", state)
    candidates = state.pending_action.get("candidates", [])
    assert len(candidates) >= 2

    r = orchestrator.handle_user_message("第二个", state)
    assert r["trace"]["fallbackUsed"] is False
    assert len(state.current_order) == 1
    # Must be the candidate's second item, not recommendation's second
    assert state.current_order[0].name == candidates[1]["name"]
    assert state.pending_action is None


def test_ambiguous_context_switch_clears_pending():
    """牛肉那个→有什么喝的: new menu query clears old candidate pending."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉那个", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "select_ambiguous_dish_candidate"

    # New menu question — should clear or overwrite old candidates
    r = orchestrator.handle_user_message("有什么喝的", state)
    assert r["trace"]["fallbackUsed"] is False
    # Old ambiguous candidates should not interfere
    assert state.pending_action is None or state.pending_action.get("type") != "select_ambiguous_dish_candidate", (
        "Old ambiguous candidates must not survive new menu query"
    )


# ═══════════════════════════════════════════════════════════════════════
# Round 4 — P2: Remaining confirm_clear_order paths
# ═══════════════════════════════════════════════════════════════════════

def test_order_by_preference_clears_confirm_clear_order():
    """_order_by_preference handler clears confirm_clear_order (direct test)."""
    from app.models.schemas import Interpretation
    from app.state.session_state import SessionState as SS

    orchestrator = OrchestratorAgent()
    state = SS()

    # Set up: add item, then set confirm_clear_order
    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    # Directly test _order_by_preference handler
    interp = Interpretation(
        intent="order_by_preference",
        confidence=0.9,
        source="rule",
        should_mutate_order=True,
        preferences={"options": ["不辣"]},
    )
    result = orchestrator.order_agent._order_by_preference(interp, state)
    patch = result.get("patch", {})
    orchestrator._apply_patch(state, patch)

    # Old order should be cleared, only new preference item remains
    assert "牛肉饭" not in [e.name for e in state.current_order], (
        "Old beef rice must be cleared when reordering via preference"
    )
    assert state.pending_action is None, "pending_action must be cleared"


def test_order_category_items_clears_confirm_clear_order():
    """牛肉饭→不要了→小吃各来一份: old cleared, new category items added."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # 小吃 has 2 items (len <= 3), so it adds directly
    orchestrator.handle_user_message("小吃各来一份吧", state)
    assert state.pending_action is None or state.pending_action.get("type") != "confirm_clear_order"
    if len(state.current_order) > 0:
        assert "牛肉饭" not in [e.name for e in state.current_order]
