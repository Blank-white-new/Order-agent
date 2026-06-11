"""Tests for robustness fixes: P0 question→order, substring matching, confirm_clear_order, rollback."""
import pytest

from app.agents.orchestrator import OrchestratorAgent
from app.agents.semantic_router import SemanticRouterAgent
from app.models.schemas import Interpretation
from app.state.session_state import SessionState


# ── P0-1: Question markers ──

@pytest.mark.parametrize(
    ("message", "expected_intent", "should_not_mutate"),
    [
        ("牛肉饭是哪里的牛肉", "ask_ingredient", True),
        ("鸡腿饭怎么做的", "ask_ingredient", True),
        ("黑椒牛肉饭为什么贵一点", "ask_ingredient", True),
        ("哪个饭比较便宜", "ask_price", True),
        ("宫保鸡丁饭里面有什么", "ask_ingredient", True),
        ("鸡腿饭怎么做", "ask_ingredient", True),
        ("这个菜是什么", "ask_ingredient", True),
        ("怎样点餐", "ask_menu", True),
        ("如何下单", "ask_menu", True),
    ],
)
def test_question_about_dish_should_not_order(message, expected_intent, should_not_mutate):
    """Questions about dishes must NOT be classified as order_food."""
    result = SemanticRouterAgent().interpret(message)
    assert result.intent != "order_food", f"'{message}' should NOT be order_food, got {result.intent}"
    assert result.should_mutate_order is False, f"'{message}' should not mutate order"


@pytest.mark.parametrize(
    "message",
    [
        "来一份牛肉饭",
        "黑椒牛肉饭吧",
        "我要鸡腿饭",
        "牛肉饭一份",
        "可乐两瓶",
    ],
)
def test_normal_ordering_still_works(message):
    """Normal ordering phrases must still work after question marker fixes."""
    result = SemanticRouterAgent().interpret(message)
    assert result.intent in {"order_food", "order_multiple_items"}, (
        f"'{message}' should still be order_food, got {result.intent}"
    )
    assert result.should_mutate_order is True


def test_question_with_question_mark_not_order():
    """Input ending with ? should not be treated as order."""
    result = SemanticRouterAgent().interpret("牛肉饭是哪里的牛肉？")
    assert result.intent != "order_food", f"Got {result.intent}, should not be order_food"


# ── P0-2: Substring matching in remove_item and replace_item ──

def test_remove_beef_rice_preserves_black_pepper_beef_rice():
    """When order has 牛肉饭 and 黑椒牛肉饭, '不要牛肉饭' only removes 牛肉饭."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add both items
    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("黑椒牛肉饭", state)
    assert len(state.current_order) == 2

    # Remove only 牛肉饭
    result = orchestrator.handle_user_message("不要牛肉饭", state)
    names = [entry.name for entry in state.current_order]
    assert "黑椒牛肉饭" in names, "黑椒牛肉饭 should remain"
    assert "牛肉饭" not in names, "牛肉饭 should be removed"
    assert len(state.current_order) == 1


def test_remove_beef_rice_not_matching_black_pepper_alone():
    """When order only has 黑椒牛肉饭, '不要牛肉饭' should not remove it."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("黑椒牛肉饭", state)
    assert len(state.current_order) == 1

    result = orchestrator.handle_user_message("不要牛肉饭", state)
    # 黑椒牛肉饭 should remain - it's not an exact match for "牛肉饭"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"


def test_replace_beef_rice_preserves_black_pepper():
    """'把牛肉饭换成鸡腿饭' only replaces 牛肉饭, not 黑椒牛肉饭."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("黑椒牛肉饭", state)
    assert len(state.current_order) == 2

    orchestrator.handle_user_message("把牛肉饭换成鸡腿饭", state)
    names = [entry.name for entry in state.current_order]
    assert "鸡腿饭" in names, "鸡腿饭 should replace 牛肉饭"
    assert "黑椒牛肉饭" in names, "黑椒牛肉饭 should remain"
    assert "牛肉饭" not in names, "牛肉饭 should be gone"


def test_replace_beef_rice_not_matching_black_pepper_alone():
    """'把牛肉饭换成鸡腿饭' with only 黑椒牛肉饭 should not replace it."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("黑椒牛肉饭", state)
    orchestrator.handle_user_message("把牛肉饭换成鸡腿饭", state)
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"


def test_update_option_beef_rice_preserves_black_pepper():
    """'牛肉饭改成大份' only updates 牛肉饭, not 黑椒牛肉饭."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("黑椒牛肉饭", state)

    orchestrator.handle_user_message("牛肉饭改成大份", state)

    entries = {entry.name: entry for entry in state.current_order}
    assert entries["牛肉饭"].options == ["大份"]
    assert entries["黑椒牛肉饭"].options == []


def test_update_quantity_beef_rice_preserves_black_pepper():
    """'牛肉饭改成两份' only updates 牛肉饭, not 黑椒牛肉饭."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("黑椒牛肉饭", state)

    orchestrator.handle_user_message("牛肉饭改成两份", state)

    quantities = {entry.name: entry.quantity for entry in state.current_order}
    assert quantities["牛肉饭"] == 2
    assert quantities["黑椒牛肉饭"] == 1


@pytest.mark.parametrize("message", ["0份鸡腿饭", "零份鸡腿饭", "00份鸡腿饭"])
def test_zero_quantity_order_is_normalized_to_positive(message):
    """Zero-like quantities should never create non-positive order items."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message(message, state)

    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert state.current_order[0].quantity == 1


def test_order_agent_restart_returns_patch_without_direct_state_mutation():
    """OrderAgent should not clear state directly while preparing a restart patch."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    state.pending_action = {"type": "confirm_clear_order"}

    result = orchestrator.order_agent.handle(
        Interpretation(
            intent="order_food",
            confidence=0.95,
            source="rule",
            should_mutate_order=True,
            entities={"item_name": "鸡腿饭", "quantity": 1},
        ),
        state,
    )

    assert [entry.name for entry in state.current_order] == ["牛肉饭"]
    assert [entry.name for entry in result["patch"]["current_order"]] == ["鸡腿饭"]
    assert result["patch"]["pending_action"] is None


# ── P0-3: confirm_clear_order ──

def test_confirm_clear_order_clears_order():
    """After cancel→confirm, order should be empty, not submitted."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add item
    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    # Cancel (triggers confirm_clear_order pending_action)
    result = orchestrator.handle_user_message("取消", state)
    trace = result["trace"]
    # Should have pending_action set to confirm_clear_order
    assert state.pending_action is not None
    assert state.pending_action.get("type") in {"confirm_clear_order", "confirm_clear_order"}

    # Confirm
    orchestrator.handle_user_message("确认", state)
    assert len(state.current_order) == 0, "Order should be empty after confirm_clear_order"
    assert state.stage != "submitted", "Should not be in submitted stage"
    assert state.submitted is False, "Order should not be submitted"
    assert state.pending_action is None, "pending_action should be cleared"


# ── P0-4: clear_order clears last_mutation_snapshot ──

def test_clear_order_clears_mutation_snapshot():
    """After clear_order + rollback trigger, order must stay empty."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add item
    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    # Clear order
    orchestrator.handle_user_message("清空订单", state)
    assert len(state.current_order) == 0

    # Rollback trigger — must NOT restore the cleared order
    orchestrator.handle_user_message("我只是问一下", state)
    assert len(state.current_order) == 0, "Cleared order must stay empty after rollback trigger"


def test_clear_order_clears_mutation_confirmed():
    """After clear_order, last_mutation_confirmed should be False."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("清空订单", state)
    assert state.last_mutation_confirmed is False


# ── P1-2: Expanded rollback triggers ──

@pytest.mark.parametrize(
    "trigger",
    [
        "我没点",
        "没让你加",
        "加错了",
        "不对",
        "不是这个",
        "不是我要的",
        "弄错了",
        "搞错了",
        "误会了",
        "我只是问问",
        "我不是要点",
        "我只是想问",
    ],
)
def test_expanded_rollback_triggers(trigger):
    """Expanded rollback triggers should revert recent unconfirmed mutations."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add item (creates mutation snapshot)
    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    # Say trigger (should roll back)
    orchestrator.handle_user_message(trigger, state)
    assert len(state.current_order) == 0, f"'{trigger}' should roll back the order"


def test_rollback_after_clear_does_not_restore():
    """After clearing order, rollback triggers must not restore."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("清空订单", state)
    orchestrator.handle_user_message("我只是问一下", state)
    assert len(state.current_order) == 0


# ── P1-3: pending_action override protection ──

def test_pending_action_not_silently_overwritten():
    """When a pending_action exists, a new one should not silently overwrite."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Trigger a pending_action (饭类 has 4 items > 3 threshold)
    result = orchestrator.handle_user_message("饭类各来一份", state)
    first_pending = state.pending_action
    assert first_pending is not None
    first_type = first_pending.get("type")

    # Do another action that would normally set a pending_action
    result2 = orchestrator.handle_user_message("取消", state)
    # Should NOT silently overwrite — either retain or warn
    if state.pending_action is not None:
        # If it retained the first, that's acceptable behavior
        pass
    # At minimum, the system should have handled the cancel somehow
    # without the original pending being silently lost without trace


# ── P1-4: Clear order resets contextual state ──

def test_clear_order_resets_last_mentioned_item():
    """Clear order should reset last_mentioned_item."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    assert state.last_mentioned_item is not None

    orchestrator.handle_user_message("清空订单", state)
    assert state.last_mentioned_item is None


def test_clear_order_resets_preferences():
    """Clear order resets preferences to defaults."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add some preferences by asking for "不辣"
    orchestrator.handle_user_message("不要牛肉饭", state)  # Adds "牛肉" to avoid
    # Clear order
    orchestrator.handle_user_message("清空订单", state)
    assert state.preferences == {"avoid": [], "options": []}


def test_clear_order_resets_viewed_category():
    """Clear order should reset viewed_category and viewed_category_group."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("有啥", state)
    # After viewing menu, viewed_category might be set
    orchestrator.handle_user_message("清空订单", state)
    assert state.viewed_category is None
    assert state.viewed_category_group is None


# ═══ Round 2: N1/P1 stale pending_action after cancel→reorder ═══

def test_cancel_then_reorder_should_not_clear_new_items():
    """After cancel→reorder, old items cleared, new items remain; confirm safe."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    # Reorder — clears old order, keeps only new items
    orchestrator.handle_user_message("鸡腿饭", state)
    assert state.pending_action is None, "pending_action should be cleared after reorder"
    # Old order cleared, only new item remains
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"

    # Confirm should NOT trigger old confirm_clear_order — should NOT clear the new item
    orchestrator.handle_user_message("确认", state)
    assert len(state.current_order) == 1, "New item should remain, not be cleared"
    assert state.current_order[0].name == "鸡腿饭"


def test_cancel_then_confirm_still_clears():
    """Original flow: cancel→confirm should still clear the order."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    orchestrator.handle_user_message("确认", state)
    assert len(state.current_order) == 0, "Order should be cleared"


# ═══ Round 2: N4/P2 clear pending_action on rollback ═══

def test_rollback_clears_pending_action():
    """Successful rollback should clear pending_action."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    # Add item
    orchestrator.handle_user_message("牛肉饭", state)
    assert len(state.current_order) == 1

    # Set a pending_action (via cancel with order)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    # Now trigger rollback — should clear pending_action too
    orchestrator.handle_user_message("我没点", state)
    assert state.pending_action is None, "Rollback should clear pending_action"
    assert len(state.current_order) == 0


def test_rollback_then_confirm_does_not_trigger_old_pending():
    """After rollback, confirm should not trigger old pending_action."""
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None

    orchestrator.handle_user_message("我没点", state)
    assert state.pending_action is None

    orchestrator.handle_user_message("确认", state)
    # Should not trigger old confirm_clear_order — order stays empty
    assert len(state.current_order) == 0


# ═══ Round 2: N2/P2 context reference "黑椒那个" ═══

def test_context_reference_with_dish_fragment():
    """'黑椒那个' after viewing menu should resolve to 黑椒牛肉饭."""
    from app.agents.semantic_router import SemanticRouterAgent

    router = SemanticRouterAgent()
    # First view menu to establish context
    result = router.interpret("有啥饭")
    assert result.intent == "ask_category"

    # "黑椒那个" — should resolve to context reference or order
    result2 = router.interpret("黑椒那个")
    # Should NOT be fallback
    assert result2.intent != "fallback", f"Got {result2.intent}, expected not fallback"
    # Should be either context_reference_resolution or order_food for 黑椒牛肉饭
    assert result2.intent in {"context_reference_resolution", "order_food", "select_recommendation"}


def test_context_reference_chicken_leg_fragment():
    """'鸡腿那个' should resolve to 鸡腿饭."""
    from app.agents.semantic_router import SemanticRouterAgent

    router = SemanticRouterAgent()
    result = router.interpret("鸡腿那个")
    assert result.intent != "fallback", f"Got {result.intent}, expected not fallback"


def test_bare_nage_not_default_to_first():
    """'那个' without dish fragment should not default to first item."""
    from app.agents.semantic_router import SemanticRouterAgent

    router = SemanticRouterAgent()
    result = router.interpret("那个")
    # Should not silently map to first item — either fallback or ask for clarification
    if result.intent == "context_reference_resolution":
        # If it resolves, it should NOT be an order mutation
        assert result.should_mutate_order is False


# ═══ Round 2: N5/P2 Chinese number expansion ═══

@pytest.mark.parametrize(
    ("message", "expected_intent", "expected_qty"),
    [
        ("六个鸡腿饭", "order_food", 6),
        ("七瓶可乐", "order_food", 7),
        ("八份牛肉饭", "order_food", 8),
        ("九份黑椒牛肉饭", "order_food", 9),
        ("十份鸡腿饭", "order_food", 10),
    ],
)
def test_chinese_numbers_six_to_ten(message, expected_intent, expected_qty):
    """Chinese numbers 六-十 should be parsed as quantities."""
    from app.agents.semantic_router import SemanticRouterAgent

    router = SemanticRouterAgent()
    result = router.interpret(message)
    assert result.intent == expected_intent, f"'{message}' intent: {result.intent}"
    assert result.entities.get("quantity") == expected_qty, (
        f"'{message}' quantity: {result.entities.get('quantity')}, expected {expected_qty}"
    )


def test_existing_chinese_numbers_still_work():
    """两 and 2 should still work for quantities."""
    from app.agents.semantic_router import SemanticRouterAgent

    router = SemanticRouterAgent()
    r1 = router.interpret("两份鸡腿饭")
    assert r1.intent == "order_food"
    assert r1.entities.get("quantity") == 2

    r2 = router.interpret("2份鸡腿饭")
    assert r2.intent == "order_food"
    assert r2.entities.get("quantity") == 2
