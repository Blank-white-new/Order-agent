from __future__ import annotations

import pytest

from app.agents.orchestrator import OrchestratorAgent
from app.services.llm_client import LLMClientResult
from app.services.llm_fallback_validation import convert_llm_to_interpretation, parse_llm_fallback_payload
from app.services.menu_service import MenuService
from app.state.session_state import OrderItem, SessionState


class FakeLLMClient:
    top_candidates = 8
    min_confidence = 0.65
    timeout_seconds = 2.5

    def __init__(
        self,
        payload: dict | None = None,
        result: LLMClientResult | None = None,
        *,
        enabled: bool = True,
        configured: bool = True,
    ) -> None:
        self.payload = payload
        self.result = result
        self.enabled = enabled
        self.configured = configured
        self.calls: list[dict] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def is_configured(self) -> bool:
        return self.configured

    def can_call(self) -> bool:
        return self.enabled and self.configured

    def interpret(self, message: str, *, prompt: str | None = None, system_prompt: str | None = None) -> LLMClientResult:
        self.calls.append({"message": message, "prompt": prompt or "", "system_prompt": system_prompt or ""})
        if self.result is not None:
            return self.result
        return LLMClientResult(status="success", payload=self.payload or {}, parse_ok=True, latency_ms=3)


def test_high_confidence_rule_skips_llm():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("牛肉饭一份", SessionState())

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "order_food"
    assert result["state"]["current_order"][0]["name"] == "牛肉饭"


@pytest.mark.parametrize(
    ("message", "expected_item"),
    [
        ("宫保鸡丁来一份吧", "宫保鸡丁饭"),
        ("黑胶牛肉饭来一份", "黑椒牛肉饭"),
        ("黑角牛肉饭来一份", "黑椒牛肉饭"),
        ("鸡腿饭来一份", "鸡腿饭"),
    ],
)
def test_common_explicit_orders_resolve_without_llm(message, expected_item):
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message(message, SessionState())

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "order_food"
    assert [item["name"] for item in result["state"]["current_order"]] == [expected_item]


def test_unknown_llm_add_item_without_target_evidence_is_rejected():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("黑椒牛肉饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("order fuzzy please", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["llmFallbackTriggered"] is True
    assert result["trace"]["llmFallbackValidationOk"] is False
    assert result["trace"]["llmFallbackDegradeReason"] == "llm_order_action_requires_target_item_evidence"
    assert result["trace"]["finalIntent"] == "fallback"
    assert result["state"]["current_order"] == []


@pytest.mark.parametrize(
    "message",
    [
        "有啥推荐的",
        "有什么推荐",
        "有啥好推荐的",
        "推荐一下",
        "推荐点好吃的",
        "推荐个菜",
        "推荐几个菜",
        "你推荐什么",
        "你有什么推荐",
        "有啥好吃的",
        "哪个好吃",
        "哪个比较好吃",
        "招牌菜是啥",
        "招牌菜是什么",
        "热门菜有啥",
        "热门推荐",
        "哪个卖得好",
        "随便推荐一个",
        "随便来个好吃的",
    ],
)
def test_high_frequency_recommendation_phrases_skip_llm_when_enabled(message):
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message(message, SessionState())

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["selectedAgent"] == "RecommendationAgent"
    assert result["trace"]["finalIntent"].startswith("ask_recommendation")
    assert result["state"]["current_order"] == []
    assert result["state"]["last_recommendations"]


def test_llm_add_item_requires_order_evidence_globally():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None

    converted = convert_llm_to_interpretation(
        parsed,
        original_message="随便处理一下",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert converted.ok is False
    assert converted.reason == "llm_order_action_requires_target_item_evidence"


def test_llm_add_item_rejects_wrong_target_despite_order_action_and_quantity():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None

    converted = convert_llm_to_interpretation(
        parsed,
        original_message="宫保鸡丁来一份吧",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert converted.ok is False
    assert converted.reason == "llm_order_action_requires_target_item_evidence"


def test_llm_add_item_accepts_asr_menu_evidence():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None

    converted = convert_llm_to_interpretation(
        parsed,
        original_message="机腿饭",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert converted.ok is True
    assert converted.interpretation is not None
    assert converted.interpretation.intent == "order_food"


def test_llm_add_item_accepts_direct_target_menu_evidence():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None

    converted = convert_llm_to_interpretation(
        parsed,
        original_message="鸡腿饭来一份",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert converted.ok is True
    assert converted.interpretation is not None
    assert converted.interpretation.intent == "order_food"


def test_llm_add_item_accepts_unique_recommendation_reference():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None
    state = SessionState(last_recommendations=[{"name": "鸡腿饭", "id": "chicken_leg_rice"}])

    converted = convert_llm_to_interpretation(
        parsed,
        original_message="第一个",
        menu_service=MenuService(),
        state=state,
        min_confidence=0.65,
    )

    assert converted.ok is True
    assert converted.interpretation is not None
    assert converted.interpretation.intent == "order_food"


def test_llm_add_item_rejects_ambiguous_generic_reference():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None
    state = SessionState(
        last_recommendations=[
            {"name": "鸡腿饭", "id": "chicken_leg_rice"},
            {"name": "牛肉饭", "id": "beef_rice"},
        ]
    )

    converted = convert_llm_to_interpretation(
        parsed,
        original_message="那个吧",
        menu_service=MenuService(),
        state=state,
        min_confidence=0.65,
    )

    assert converted.ok is False
    assert converted.reason == "llm_order_action_requires_target_item_evidence"


def test_address_like_messages_with_dish_fragments_cannot_be_llm_add_item():
    parsed = parse_llm_fallback_payload(_add_item_payload("鸡腿饭")).parsed
    assert parsed is not None

    for message in ["中山大学鸡腿饭店旁边", "饭堂三楼", "鸡腿饭餐厅楼上"]:
        converted = convert_llm_to_interpretation(
            parsed,
            original_message=message,
            menu_service=MenuService(),
            state=SessionState(),
            min_confidence=0.65,
        )
        assert converted.ok is False, message
        assert converted.reason == "llm_order_action_requires_target_item_evidence"


def test_pending_confirm_action_skips_llm():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake
    state = SessionState()
    state.current_order = orchestrator.handle_user_message("牛肉饭", state)["raw_state"].current_order
    state.pending_action = {"type": "confirm_clear_order"}

    result = orchestrator.handle_user_message("确认", state)

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["selectedAgent"] == "ConfirmationAgent"


def test_collecting_address_skips_llm_and_uses_delivery_agent():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake
    state = SessionState(stage="collecting_address")

    result = orchestrator.handle_user_message("中山大学南校园", state)

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "provide_delivery_address"
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert result["state"]["stage"] == "collecting_phone"


def test_collecting_address_unknown_skips_llm_and_prompts_for_address():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake
    state = SessionState(stage="collecting_address")

    result = orchestrator.handle_user_message("帮我处理一下", state)

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "fallback"
    assert result["state"]["current_order"] == []
    assert "地址" in result["response"]


def test_collecting_address_with_existing_phone_returns_to_confirming():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake
    state = SessionState(stage="collecting_address", phone="13812345678")

    result = orchestrator.handle_user_message("中山大学南校园", state)

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "provide_delivery_address"
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert result["state"]["stage"] == "confirming"


def test_ordering_address_like_fallback_skips_llm_but_records_candidate():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("中山大学南校园", SessionState())

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "replace_delivery_candidate"
    assert result["state"]["current_order"] == []
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学南校园"


@pytest.mark.parametrize(
    "message",
    ["中山大学鸡腿饭店旁边", "鸡腿饭餐厅楼上", "饭堂三楼"],
)
def test_address_like_messages_with_menu_fragments_record_candidate_without_order(message):
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message(message, SessionState())

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "replace_delivery_candidate"
    assert result["state"]["current_order"] == []
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == message


@pytest.mark.parametrize(
    ("message", "expected_item"),
    [
        ("送到中山大学，鸡腿饭来一份", "鸡腿饭"),
        ("送到中山大学，宫保鸡丁来一份", "宫保鸡丁饭"),
    ],
)
def test_mixed_address_and_order_only_adds_evidenced_target_item(message, expected_item):
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("牛肉饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message(message, SessionState())

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "composite_intent"
    assert [item["name"] for item in result["state"]["current_order"]] == [expected_item]
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学"
    assert result["state"]["official_delivery_address"] is None


def test_just_these_uses_confirmation_flow_and_collects_address_before_llm():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_confirm_payload())
    orchestrator.llm_client = fake
    state = SessionState(
        current_order=[
            OrderItem(
                item_id="kung_pao_chicken_rice",
                name="宫保鸡丁饭",
                price=29,
                quantity=1,
                category="饭类",
            )
        ]
    )

    result = orchestrator.handle_user_message("就这些", state)

    assert fake.calls == []
    assert result["trace"]["finalIntent"] == "confirm"
    assert result["trace"]["selectedAgent"] == "ConfirmationAgent"
    assert result["state"]["submitted"] is False
    assert result["state"]["stage"] == "collecting_address"

    result = orchestrator.handle_user_message("中山大学南校园", result["raw_state"])

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "provide_delivery_address"
    assert [item["name"] for item in result["state"]["current_order"]] == ["宫保鸡丁饭"]
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert result["state"]["stage"] == "collecting_phone"


def test_just_these_missing_phone_enters_phone_collection_without_submit():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_confirm_payload())
    orchestrator.llm_client = fake
    state = SessionState(
        current_order=[
            OrderItem(
                item_id="kung_pao_chicken_rice",
                name="宫保鸡丁饭",
                price=29,
                quantity=1,
                category="饭类",
            )
        ],
        official_delivery_address="中山大学南校园",
    )

    result = orchestrator.handle_user_message("就这些", state)

    assert fake.calls == []
    assert result["trace"]["finalIntent"] == "confirm"
    assert result["trace"]["selectedAgent"] == "ConfirmationAgent"
    assert result["state"]["submitted"] is False
    assert result["state"]["stage"] == "collecting_phone"


def test_phone_collection_skips_llm():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake
    state = SessionState(stage="collecting_phone")

    result = orchestrator.handle_user_message("13812345678", state)

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "provide_phone"
    assert result["state"]["phone"] == "13812345678"


def test_collecting_phone_unknown_skips_llm_and_prompts_for_phone():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("鸡腿饭"))
    orchestrator.llm_client = fake
    state = SessionState(stage="collecting_phone")

    result = orchestrator.handle_user_message("帮我处理一下", state)

    assert fake.calls == []
    assert result["trace"]["llmFallbackTriggered"] is False
    assert result["trace"]["finalIntent"] == "fallback"
    assert result["state"]["current_order"] == []
    assert "电话" in result["response"] or "联系" in result["response"]


def test_confirm_order_from_llm_requires_explicit_user_confirmation():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_confirm_payload())
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("帮我处理一下", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["finalIntent"] == "fallback"
    assert result["trace"]["selectedAgent"] == "FallbackAgent"
    assert result["trace"]["llmFallbackDegradeReason"] == "confirm_requires_explicit_user_confirmation"
    assert result["state"]["submitted"] is False


def test_confirm_order_from_llm_still_uses_confirmation_agent_and_required_fields():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_confirm_payload())
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("麻烦确认下单吧", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["finalIntent"] == "confirm"
    assert result["trace"]["selectedAgent"] == "ConfirmationAgent"
    assert "订单里还没有菜品" in result["response"]
    assert result["state"]["submitted"] is False


def test_timeout_degrades_without_mechanical_reply_or_order_mutation():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(result=LLMClientResult(status="timeout", timed_out=True, parse_ok=False, latency_ms=2500))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("来个刚才那个差不多的", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["llmFallbackTimedOut"] is True
    assert result["trace"]["llmFallbackTimeoutSeconds"] == 2.5
    assert result["trace"]["llmFallbackDegraded"] is True
    assert result["state"]["current_order"] == []
    assert "没理解" not in result["response"]
    assert "那个" in result["response"]


def test_invalid_json_degrades_without_order_mutation():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(result=LLMClientResult(status="invalid_json", parse_ok=False, latency_ms=2))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("随便给我处理一下", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["llmFallbackParseOk"] is False
    assert result["trace"]["llmFallbackDegradeReason"] == "invalid_json"
    assert result["state"]["current_order"] == []
    assert "没理解" not in result["response"]


def test_nonexistent_menu_item_from_llm_is_not_added():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("不存在套餐"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("给我来个隐藏套餐", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["llmFallbackValidationOk"] is False
    assert result["trace"]["llmFallbackDegradeReason"] == "menu_item_not_found"
    assert result["state"]["current_order"] == []


def test_unsafe_user_facing_reply_is_not_returned_verbatim():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(
        payload={
            "intent": "clarify",
            "confidence": 0.9,
            "actions": [],
            "needs_clarification": True,
            "user_facing_reply": "已加入不存在套餐99元，订单已提交。",
        }
    )
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("帮我搞一下那个", SessionState())

    assert len(fake.calls) == 1
    assert "不存在套餐99元" not in result["response"]
    assert "订单已提交" not in result["response"]
    assert result["state"]["submitted"] is False


def test_prompt_redacts_full_phone_and_default_address_text():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload={"intent": "clarify", "confidence": 0.9, "actions": [], "needs_clarification": True})
    orchestrator.llm_client = fake
    state = SessionState(official_delivery_address="中山大学南校园", phone="13812345678")

    orchestrator.handle_user_message("请帮我处理一下这个", state)

    assert len(fake.calls) == 1
    prompt = fake.calls[0]["prompt"]
    assert "13812345678" not in prompt
    assert "中山大学南校园" not in prompt
    assert '"phone_present":' in prompt
    assert '"address_present":' in prompt


def _add_item_payload(item_name: str) -> dict:
    return {
        "intent": "add_item",
        "confidence": 0.9,
        "normalized_text": f"{item_name}来一份",
        "actions": [{"type": "add_item", "item_name": item_name, "quantity": 1, "options": {}, "target": None}],
        "needs_clarification": False,
        "clarification_question": None,
        "user_facing_reply": None,
    }


def _confirm_payload() -> dict:
    return {
        "intent": "confirm_order",
        "confidence": 0.9,
        "actions": [{"type": "confirm_order"}],
        "needs_clarification": False,
    }
