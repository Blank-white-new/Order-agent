from __future__ import annotations

from app.agents.orchestrator import OrchestratorAgent
from app.services.llm_client import LLMClientResult
from app.state.session_state import SessionState


class FakeLLMClient:
    top_candidates = 8
    min_confidence = 0.65

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


def test_unknown_can_trigger_mock_llm_and_add_existing_menu_item():
    orchestrator = OrchestratorAgent()
    fake = FakeLLMClient(payload=_add_item_payload("黑椒牛肉饭"))
    orchestrator.llm_client = fake

    result = orchestrator.handle_user_message("order fuzzy please", SessionState())

    assert len(fake.calls) == 1
    assert result["trace"]["llmFallbackTriggered"] is True
    assert result["trace"]["llmFallbackValidationOk"] is True
    assert result["trace"]["finalIntent"] == "order_food"
    assert result["trace"]["interpretationSource"] == "llm"
    assert result["state"]["current_order"][0]["name"] == "黑椒牛肉饭"


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
