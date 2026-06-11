from app.agents.orchestrator import OrchestratorAgent
from app.state.session_state import SessionState


def test_clear_order_pending_expires_after_price_question():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    assert [item.name for item in state.current_order] == ["牛肉饭"]

    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    price_result = orchestrator.handle_user_message("鸡腿饭多少钱", state)
    assert price_result["trace"]["finalIntent"] == "ask_price"
    assert state.pending_action is None

    confirm_result = orchestrator.handle_user_message("确认", state)
    assert [item.name for item in state.current_order] == ["牛肉饭"]
    assert state.pending_action is None
    assert state.submitted is False
    assert confirm_result["trace"]["selectedHandler"] == "confirm"
    assert "没有需要确认" in confirm_result["response"] or "没有菜品" not in confirm_result["response"]


def test_clear_order_pending_expires_after_recommendation_question():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("牛肉饭", state)
    orchestrator.handle_user_message("不要了", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_clear_order"

    recommendation_result = orchestrator.handle_user_message("推荐", state)
    assert recommendation_result["trace"]["finalIntent"] == "ask_recommendation"
    assert state.pending_action is None
    assert [item.name for item in state.current_order] == ["牛肉饭"]

    confirm_result = orchestrator.handle_user_message("确认", state)
    assert [item.name for item in state.current_order] == ["牛肉饭"]
    assert state.submitted is False
    assert "已清空" not in confirm_result["response"]


def test_cancel_prioritizes_existing_pending_action_and_preserves_order():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    orchestrator.handle_user_message("可乐", state)
    assert [item.name for item in state.current_order] == ["可乐"]

    orchestrator.handle_user_message("饭类都来一个", state)
    assert state.pending_action is not None
    assert state.pending_action.get("type") == "confirm_order_category_items"

    result = orchestrator.handle_user_message("取消", state)
    assert [item.name for item in state.current_order] == ["可乐"]
    assert state.pending_action is None
    assert "先处理完" not in result["response"]


def test_delivery_candidate_expires_after_menu_question_before_confirm():
    orchestrator = OrchestratorAgent()
    state = SessionState()

    fee_result = orchestrator.handle_user_message("中山大学南校园配送费多少", state)
    assert fee_result["trace"]["finalIntent"] == "ask_delivery_fee"
    assert state.pending_delivery_address_candidate is not None
    assert state.pending_delivery_address_candidate.normalized == "中山大学南校园"

    menu_result = orchestrator.handle_user_message("有啥", state)
    assert menu_result["trace"]["finalIntent"] == "ask_menu"
    assert state.pending_delivery_address_candidate is None

    confirm_result = orchestrator.handle_user_message("确认", state)
    assert state.official_delivery_address is None
    assert state.pending_delivery_address_candidate is None
    assert state.submitted is False
    assert confirm_result["trace"]["selectedHandler"] == "confirm"
    assert "没有需要确认" in confirm_result["response"] or "配送地址用" not in confirm_result["response"]
