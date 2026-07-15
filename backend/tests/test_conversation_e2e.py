from app.state.session_state import DeliveryAddressCandidate, OrderItem, SessionState
from .conftest import assert_trace_basics, send


def test_context_repair_empty_order(orchestrator):
    result = send(orchestrator, "刚才啥也没点啊")

    assert_trace_basics(result, agent="ContextRepairAgent", handler="context_correction", intent="context_correction")
    assert "确实还没点" in result["response"]
    assert result["state"]["current_order"] == []


def test_context_repair_i_have_not_ordered(orchestrator):
    result = send(orchestrator, "我还没点呢")

    assert_trace_basics(result, agent="ContextRepairAgent", handler="context_correction", intent="context_correction")
    assert "还没点" in result["response"]


def test_context_repair_wrong_understanding(orchestrator):
    state = SessionState(stage="confirming")
    result = send(orchestrator, "你理解错了", state)

    assert_trace_basics(result, agent="ContextRepairAgent", handler="context_correction", intent="context_correction")
    assert result["state"]["stage"] == "ordering"


def test_empty_order_confirm_cannot_submit(orchestrator):
    result = send(orchestrator, "确认")

    assert_trace_basics(result, agent="ConfirmationAgent", handler="confirm", intent="confirm")
    assert result["state"]["submitted"] is False
    assert "还没有菜品" in result["response"]


def test_complete_order_confirm_can_submit(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1)],
        fulfillment_type="delivery",
        official_delivery_address="中山大学南校园",
        phone="13800138000",
        stage="confirming",
    )
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True
    assert "订单已确认并保存到模拟系统" in result["response"]
    assert "尚未发送给真实餐厅" in result["response"]


def test_pending_candidate_confirm_confirms_address_not_order(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1)],
        pending_delivery_address_candidate=DeliveryAddressCandidate(
            raw="中山大学南校园",
            normalized="中山大学南校园",
            source="eta_question",
            confidence=0.95,
            requires_confirmation=True,
        ),
    )
    result = send(orchestrator, "可以", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="confirm_pending_address", intent="confirm_delivery_candidate")
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert result["state"]["submitted"] is False


def test_smalltalk_or_fallback_pulls_back_to_ordering(orchestrator):
    result = send(orchestrator, "今天月亮为什么这么圆")

    assert result["trace"]["selectedAgent"] in {"ResponseAgent", "FallbackAgent"}
    assert result["trace"]["finalIntent"] in {"smalltalk", "fallback"}
    assert result["state"]["current_order"] == []
    assert "点餐" in result["response"]


def test_manual_dialogs_do_not_fallback(orchestrator):
    result = send(orchestrator, "有啥")
    assert result["trace"]["fallbackUsed"] is False

    result = send(orchestrator, "有没有酒")
    assert result["trace"]["fallbackUsed"] is False

    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "鸡腿饭不辣", state)
    assert result["trace"]["fallbackUsed"] is False

    state = send(orchestrator, "中山大学南校园要送多久？")["raw_state"]
    result = send(orchestrator, "用这个地址", state)
    assert result["trace"]["fallbackUsed"] is False

    state = send(orchestrator, "饭")["raw_state"]
    result = send(orchestrator, "除了饭还有什么？", state)
    assert result["trace"]["fallbackUsed"] is False

    result = send(orchestrator, "刚才啥也没点啊")
    assert result["trace"]["fallbackUsed"] is False


def test_e2e_menu_then_category_batch_order(orchestrator):
    state = send(orchestrator, "有啥")["raw_state"]
    result = send(orchestrator, "小吃各来一份吧", state)

    assert_trace_basics(result, agent="OrderAgent", handler="order_category_items", intent="order_category_items")
    assert [item["name"] for item in result["state"]["current_order"]] == ["酸辣土豆丝", "鸡米花"]


def test_e2e_recommend_then_specific_order_with_option(orchestrator):
    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "鸡腿饭不辣", state)

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"
    assert "不辣" in result["state"]["current_order"][0]["options"]


def test_e2e_category_exclusion(orchestrator):
    state = send(orchestrator, "饭")["raw_state"]
    result = send(orchestrator, "除了饭还有什么", state)

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category", intent="ask_category")
    assert "面类" in result["response"]
    assert "牛肉饭" not in result["response"]


def test_e2e_price_question_then_order(orchestrator):
    state = send(orchestrator, "鸡腿饭多少钱")["raw_state"]
    assert state.current_order == []
    result = send(orchestrator, "鸡腿饭不辣", state)

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"


def test_e2e_eta_then_use_candidate(orchestrator):
    state = send(orchestrator, "中山大学南校园要送多久")["raw_state"]
    assert state.official_delivery_address is None
    result = send(orchestrator, "用这个地址", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="confirm_pending_address", intent="confirm_delivery_candidate")
    assert result["state"]["official_delivery_address"] == "中山大学南校园"


def test_e2e_delivery_stage_global_menu_then_address(orchestrator):
    state = send(orchestrator, "配送")["raw_state"]
    result = send(orchestrator, "有啥喝的", state)

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category", intent="ask_category")
    assert "可乐" in result["response"]
    state = result["raw_state"]
    result = send(orchestrator, "中山大学南校园", state)
    assert_trace_basics(result, agent="DeliveryAgent", handler="provide_delivery_address", intent="provide_delivery_address")
    assert result["state"]["official_delivery_address"] == "中山大学南校园"


def test_e2e_complete_delivery_order_submission(orchestrator):
    state = send(orchestrator, "鸡腿饭一份，可乐两瓶")["raw_state"]
    state = send(orchestrator, "配送", state)["raw_state"]
    state = send(orchestrator, "中山大学南校园", state)["raw_state"]
    state = send(orchestrator, "13812345678", state)["raw_state"]
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True
    assert "鸡腿饭" in result["response"]
    assert "可乐" in result["response"]


def test_e2e_complete_signature_order_closes_submission_loop(orchestrator):
    state = send(orchestrator, "招牌菜是啥")["raw_state"]
    state = send(orchestrator, "黑椒牛肉饭吧", state)["raw_state"]
    state = send(orchestrator, "再来一份", state)["raw_state"]
    state = send(orchestrator, "这个少辣", state)["raw_state"]
    state = send(orchestrator, "配送", state)["raw_state"]
    state = send(orchestrator, "中山大学深圳校区", state)["raw_state"]
    state = send(orchestrator, "13800138000", state)["raw_state"]
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True
    assert result["state"]["stage"] == "submitted"
    assert result["state"]["pending_action"] is None
    assert result["state"]["official_delivery_address"] == "中山大学深圳校区"
    assert result["state"]["phone"] == "13800138000"
    assert "还需要配送地址" not in result["response"]
    assert "还需要联系电话" not in result["response"]
    assert "订单已确认并保存到模拟系统" in result["response"]
    assert "尚未发送给真实餐厅" in result["response"]
    order = result["state"]["current_order"]
    assert len(order) == 1
    assert order[0]["name"] == "黑椒牛肉饭"
    assert order[0]["quantity"] == 2
    assert "少辣" in order[0]["options"]


def test_acceptance_inputs_do_not_fallback(orchestrator):
    messages = [
        "有啥",
        "有没有酒",
        "有啥喝的",
        "鸡腿饭多少钱",
        "鸡腿饭可以不辣吗",
        "鸡腿饭不辣",
        "小吃各来一份吧",
        "饮品都来两瓶",
        "推荐",
        "中山大学南校园要送多久",
        "到中山大学南校园配送费多少",
        "刚才啥也没点啊",
        "饭，除了饭还有什么",
        "不要牛肉饭",
        "小吃不要了",
    ]
    for message in messages:
        result = send(orchestrator, message)
        assert result["trace"]["fallbackUsed"] is False, message
        assert "没太理解" not in result["response"]

    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "第一个", state)
    assert result["trace"]["fallbackUsed"] is False


def test_e2e_short_group_ranked_then_order(orchestrator):
    state = send(orchestrator, "主食有什么")["raw_state"]
    assert state.viewed_category_group == "主食"

    result = send(orchestrator, "饭类哪个最好吃", state)
    assert_trace_basics(
        result,
        agent="RecommendationAgent",
        handler="ask_recommendation_by_category_ranked",
        intent="ask_recommendation_by_category_ranked",
    )
    assert "鸡腿饭" in result["response"]

    result = send(orchestrator, "鸡腿饭不辣", result["raw_state"])
    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"


def test_e2e_composite_order_delivery_then_submit(orchestrator):
    state = send(orchestrator, "鸡腿饭不辣，再来瓶可乐，配送到中山大学南校园要多久")["raw_state"]
    assert [item.name for item in state.current_order] == ["鸡腿饭", "可乐"]
    assert state.official_delivery_address is None
    assert state.pending_delivery_address_candidate.normalized == "中山大学南校园"

    state = send(orchestrator, "用这个地址", state)["raw_state"]
    state = send(orchestrator, "13812345678", state)["raw_state"]
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True


def test_e2e_pending_bulk_confirm(orchestrator):
    state = send(orchestrator, "有啥")["raw_state"]
    state = send(orchestrator, "饭类各来一份", state)["raw_state"]
    assert state.pending_action["type"] == "confirm_order_category_items"
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="confirm_pending_action", intent="confirm")
    assert len(result["state"]["current_order"]) == 4
