from .conftest import assert_trace_basics, send


def test_context_repair_more_phrases(orchestrator):
    for message in ["我没点东西", "哪来的订单", "不是这个", "我不是这个意思", "你说错了", "我不是要这个"]:
        result = send(orchestrator, message)
        assert_trace_basics(result, agent="ContextRepairAgent", handler="context_correction", intent="context_correction")
        assert result["trace"]["fallbackUsed"] is False
        assert result["state"]["pending_delivery_address_candidate"] is None


def test_unresolved_reference_asks_clarification(orchestrator):
    result = send(orchestrator, "刚才那个不要了")

    assert_trace_basics(result, agent="ContextRepairAgent", handler="context_correction", intent="context_correction")
    assert "具体" in result["response"] or "没点" in result["response"]
    assert result["trace"]["fallbackUsed"] is False

