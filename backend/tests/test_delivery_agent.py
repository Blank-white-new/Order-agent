from app.state.session_state import SessionState
from .conftest import assert_no_order_mutation, assert_trace_basics, send


def test_eta_question_sets_pending_candidate_only(orchestrator):
    result = send(orchestrator, "中山大学南校园要送多久？")

    assert_trace_basics(result, agent="DeliveryAgent", handler="ask_delivery_eta", intent="ask_delivery_eta")
    assert "分钟" in result["response"]
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学南校园"
    assert_no_order_mutation(result)


def test_delivery_fee_question_sets_pending_candidate_only(orchestrator):
    result = send(orchestrator, "到中山大学南校园配送费多少？")

    assert_trace_basics(result, agent="DeliveryAgent", handler="ask_delivery_fee", intent="ask_delivery_fee")
    assert "配送费" in result["response"]
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["source"] == "fee_question"


def test_deliverability_question_sets_pending_candidate_only(orchestrator):
    result = send(orchestrator, "中山大学南校园能送吗？")

    assert_trace_basics(result, agent="DeliveryAgent", handler="ask_deliverability", intent="ask_deliverability")
    assert "可以送" in result["response"]
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["source"] == "deliverability_question"


def test_eta_without_address_asks_for_address(orchestrator):
    result = send(orchestrator, "外卖多久？")

    assert_trace_basics(result, agent="DeliveryAgent", handler="ask_delivery_eta", intent="ask_delivery_eta")
    assert "地址" in result["response"]
    assert result["state"]["official_delivery_address"] is None


def test_fee_without_address_asks_for_address(orchestrator):
    result = send(orchestrator, "配送费多少？")

    assert_trace_basics(result, agent="DeliveryAgent", handler="ask_delivery_fee", intent="ask_delivery_fee")
    assert "地址" in result["response"]
    assert result["state"]["official_delivery_address"] is None


def test_deliverability_without_address_asks_for_address(orchestrator):
    result = send(orchestrator, "这个地址能送到吗？")

    assert_trace_basics(result, agent="DeliveryAgent", handler="ask_deliverability", intent="ask_deliverability")
    assert "地址" in result["response"]
    assert result["state"]["official_delivery_address"] is None


def test_delivery_stage_menu_intent_not_treated_as_address(orchestrator):
    state = SessionState(stage="collecting_address")
    result = send(orchestrator, "有啥喝的", state)

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category", intent="ask_category")
    assert result["state"]["official_delivery_address"] is None


def test_plain_address_in_delivery_stage_writes_official_address(orchestrator):
    state = SessionState(stage="collecting_address")
    result = send(orchestrator, "中山大学南校园", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="provide_delivery_address", intent="provide_delivery_address")
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert "电话" in result["response"]


def test_confirm_pending_eta_candidate_writes_address_not_order(orchestrator):
    state = send(orchestrator, "中山大学南校园要送多久？")["raw_state"]
    result = send(orchestrator, "用这个地址", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="confirm_pending_address", intent="confirm_delivery_candidate")
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert result["state"]["submitted"] is False


def test_new_address_replaces_pending_candidate(orchestrator):
    state = send(orchestrator, "中山大学南校园要送多久？")["raw_state"]
    result = send(orchestrator, "华南理工大学北门", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="provide_delivery_address", intent="replace_delivery_candidate")
    assert result["state"]["official_delivery_address"] == "华南理工大学北门"
    assert result["state"]["pending_delivery_address_candidate"] is None


def test_reject_pending_candidate_clears_only_candidate(orchestrator):
    state = send(orchestrator, "中山大学南校园要送多久？")["raw_state"]
    result = send(orchestrator, "不用", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="reject_pending_address", intent="reject_delivery_candidate")
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"] is None
    assert result["state"]["submitted"] is False


def test_fulfillment_delivery_and_pickup(orchestrator):
    result = send(orchestrator, "配送")

    assert_trace_basics(result, agent="DeliveryAgent", handler="provide_fulfillment_slot", intent="provide_fulfillment_slot")
    assert result["state"]["fulfillment_type"] == "delivery"
    assert result["state"]["stage"] == "collecting_address"

    result = send(orchestrator, "自取")
    assert_trace_basics(result, agent="DeliveryAgent", handler="provide_fulfillment_slot", intent="provide_fulfillment_slot")
    assert result["state"]["fulfillment_type"] == "pickup"
    assert result["state"]["official_delivery_address"] is None


def test_plain_address_outside_address_stage_becomes_candidate(orchestrator):
    result = send(orchestrator, "中山大学南校园")

    assert_trace_basics(result, agent="DeliveryAgent", handler="address_candidate", intent="replace_delivery_candidate")
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学南校园"


def test_phone_collection(orchestrator):
    state = SessionState(stage="collecting_phone")
    result = send(orchestrator, "电话 13812345678", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="provide_phone", intent="provide_phone")
    assert result["state"]["phone"] == "13812345678"
    assert result["state"]["stage"] == "confirming"
