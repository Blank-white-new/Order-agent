from app.agents.orchestrator import OrchestratorAgent
from app.state.session_state import SessionState


def test_repeat_last_item_adds_quantity():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("鸡腿饭", state)
    result = orchestrator.handle_user_message("再来一份", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "repeat_last_item"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert state.current_order[0].quantity == 2
    assert state.last_mentioned_item == "鸡腿饭"


def test_replace_single_existing_item_with_new_item():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    result = orchestrator.handle_user_message("换成鸡腿饭", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "replace_item"
    assert [item.name for item in state.current_order] == ["鸡腿饭"]
    assert "牛肉饭" not in [item.name for item in state.current_order]
    assert state.last_mentioned_item == "鸡腿饭"


def test_context_reference_modify_last_item_options():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉面", state)
    result = orchestrator.handle_user_message("这个不要香菜", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "update_item_option"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "牛肉面"
    assert "不要香菜" in state.current_order[0].options


def test_explicit_item_name_modifies_existing_item_options():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉面", state)
    result = orchestrator.handle_user_message("牛肉面不要香菜", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "update_item_option"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "牛肉面"
    assert "不要香菜" in state.current_order[0].options


def test_context_reference_modify_spicy_option():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("鸡腿饭", state)
    result = orchestrator.handle_user_message("这个少辣", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "update_item_option"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "鸡腿饭"
    assert "少辣" in state.current_order[0].options


def test_unsupported_option_saved_as_item_note():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    result = orchestrator.handle_user_message("这个不要香菜", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "update_item_option"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "牛肉饭"
    assert state.current_order[0].quantity == 1
    assert "不要香菜" not in state.current_order[0].options
    assert state.current_order[0].notes is not None
    assert "不要香菜" in state.current_order[0].notes
    assert "已备注" in result["response"]


def test_explicit_item_unsupported_option_saved_as_note():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    result = orchestrator.handle_user_message("牛肉饭不要香菜", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "update_item_option"
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "牛肉饭"
    assert state.current_order[0].quantity == 1
    assert "不要香菜" not in state.current_order[0].options
    assert state.current_order[0].notes is not None
    assert "不要香菜" in state.current_order[0].notes


def test_supported_option_still_uses_options():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("鸡腿饭", state)
    result = orchestrator.handle_user_message("这个少辣", state)

    assert result["trace"]["fallbackUsed"] is False
    assert result["trace"]["finalIntent"] == "update_item_option"
    assert len(state.current_order) == 1
    assert "少辣" in state.current_order[0].options
    assert state.current_order[0].notes is None


def test_notes_appear_in_confirmation_summary():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("这个不要香菜", state)
    orchestrator.handle_user_message("配送", state)
    orchestrator.handle_user_message("中山大学深圳校区", state)
    orchestrator.handle_user_message("13800138000", state)
    result = orchestrator.handle_user_message("确认", state)

    assert result["trace"]["selectedHandler"] == "submit_order"
    assert state.submitted is True
    assert state.pending_action is None
    assert state.current_order[0].notes is not None
    assert "不要香菜" in state.current_order[0].notes
    assert "不要香菜" in result["response"]


def test_replace_does_not_leave_stale_pending_action():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    replace_result = orchestrator.handle_user_message("换成鸡腿饭", state)
    confirm_result = orchestrator.handle_user_message("确认", state)

    assert replace_result["trace"]["fallbackUsed"] is False
    assert state.pending_action is None
    assert [item.name for item in state.current_order] == ["鸡腿饭"]
    assert state.submitted is False
    assert confirm_result["trace"]["selectedHandler"] == "confirm"
    assert "已清空" not in confirm_result["response"]
