from __future__ import annotations

import json
import re
from pathlib import Path

from app.agents.orchestrator import OrchestratorAgent
from app.models.schemas import Interpretation
from app.services import llm_client as llm_module
from app.services.llm_client import LLMClient, LLMClientResult, create_llm_fallback_client
from app.services.llm_fallback_modes import LLMRuntimeMode, describe_llm_runtime_safety
from app.services.llm_fallback_validation import convert_llm_to_interpretation, parse_llm_fallback_payload
from app.services.llm_replay_client import InMemoryFakeLLMClient, ReplayLLMClient, ShadowLLMClient
from app.services.menu_service import MenuService
from app.state.session_state import SessionState


FIXTURES = Path(__file__).with_name("fixtures") / "llm_replay"


class NetworkBlocker:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("sandbox must not call network")


def test_default_disabled_ignores_enabled_and_present_key(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODE", "disabled")
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fake-but-present")
    blocker = NetworkBlocker()

    client = LLMClient(http_client=blocker)
    result = client.interpret("帮我处理一下")

    assert client.runtime_mode == "disabled"
    assert client.api_key is None
    assert client.can_call() is False
    assert result.status == "disabled"
    assert blocker.calls == 0


def test_unknown_mode_fails_closed_without_network(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODE", "unknown")
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("ALLOW_LIVE_LLM", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fake-but-present")
    llm_module._env_file_values.cache_clear()

    client = create_llm_fallback_client()

    assert client.runtime_mode == "disabled"
    assert client.can_call() is False
    assert client.config_error == "unknown_llm_fallback_mode:unknown"


def test_live_requires_all_three_opt_ins(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODE", "live")
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("ALLOW_LIVE_LLM", "false")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fake-test-key")
    blocker = NetworkBlocker()

    client = LLMClient(http_client=blocker)

    assert client.can_call() is False
    assert client.interpret("test").status == "live_not_allowed"
    assert blocker.calls == 0


def test_safe_runtime_description_never_contains_credentials():
    description = describe_llm_runtime_safety(
        mode=LLMRuntimeMode.SHADOW,
        enabled=True,
        allow_live=False,
        sandbox_source="fake",
    )

    assert description["networkAllowed"] is False
    assert description["shadow"] is True
    assert not any("key" in key.lower() or "secret" in key.lower() for key in description)


def test_fake_candidate_still_passes_schema_and_business_validation():
    payload = json.loads((FIXTURES / "valid_add_item.json").read_text(encoding="utf-8"))
    fake = InMemoryFakeLLMClient(payload)

    result = fake.interpret("黑椒牛肉饭来一份")
    parsed = parse_llm_fallback_payload(result.payload or {})
    converted = convert_llm_to_interpretation(
        parsed.parsed,
        original_message="黑椒牛肉饭来一份",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert result.ok is True
    assert parsed.ok is True
    assert converted.ok is True
    assert converted.interpretation is not None
    assert converted.interpretation.should_mutate_order is True
    assert fake.network_allowed is False


def test_fake_malformed_candidate_is_rejected():
    fake = InMemoryFakeLLMClient(LLMClientResult(status="invalid_json", parse_ok=False))

    result = fake.interpret("anything")

    assert result.status == "invalid_json"
    assert result.ok is False


def test_replay_valid_and_invalid_candidates_are_validated():
    valid_result = ReplayLLMClient(FIXTURES / "valid_add_item.json").interpret("ignored")
    invalid_result = ReplayLLMClient(FIXTURES / "invalid_fabricated_item.json").interpret("ignored")
    valid = parse_llm_fallback_payload(valid_result.payload or {})
    invalid = parse_llm_fallback_payload(invalid_result.payload or {})

    valid_converted = convert_llm_to_interpretation(
        valid.parsed,
        original_message="黑椒牛肉饭来一份",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )
    invalid_converted = convert_llm_to_interpretation(
        invalid.parsed,
        original_message="虚构套餐来一份",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert valid_converted.ok is True
    assert invalid_converted.ok is False
    assert invalid_converted.reason == "menu_item_not_found"


def test_replay_missing_or_malformed_file_never_falls_back_to_live(tmp_path):
    missing = ReplayLLMClient(tmp_path / "missing.json")
    malformed = ReplayLLMClient(FIXTURES / "malformed_response.json")
    forbidden = ReplayLLMClient(tmp_path / ".env")

    assert missing.interpret("ignored").status == "replay_file_not_found"
    assert malformed.interpret("ignored").status == "invalid_json"
    assert forbidden.interpret("ignored").status == "unsafe_replay_path"
    assert missing.network_allowed is False
    assert malformed.network_allowed is False


def test_replay_fixtures_do_not_contain_sensitive_values():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURES.glob("*.json"))

    assert "sk-" not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
    assert re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", combined) is None
    assert "大学" not in combined and "路" not in combined and "手机号" not in combined


def test_replay_unsafe_user_reply_is_removed_by_validation():
    result = ReplayLLMClient(FIXTURES / "unsafe_user_facing_reply.json").interpret("ignored")
    parsed = parse_llm_fallback_payload(result.payload or {})
    converted = convert_llm_to_interpretation(
        parsed.parsed,
        original_message="帮我处理一下",
        menu_service=MenuService(),
        state=SessionState(),
        min_confidence=0.65,
    )

    assert converted.ok is True
    assert converted.safe_reply is None


def test_shadow_validates_would_mutate_but_preserves_entire_session_state():
    payload = json.loads((FIXTURES / "valid_add_item.json").read_text(encoding="utf-8"))
    orchestrator = OrchestratorAgent()
    orchestrator.llm_client = ShadowLLMClient(InMemoryFakeLLMClient(payload))
    orchestrator.semantic_router.interpret = lambda _message: Interpretation(
        intent="fallback", confidence=0.2, source="deterministic", should_mutate_order=False
    )
    state = SessionState(official_delivery_address="示例大学一号楼", phone="13800000000")
    before = state.serializable()

    result = orchestrator.handle_user_message("order 黑椒牛肉饭 please", state)

    assert result["state"] == before
    assert result["trace"]["llmFallbackShadow"] is True
    assert result["trace"]["llmFallbackShadowCandidate"] is True
    assert result["trace"]["llmFallbackValidationAccepted"] is True
    assert result["trace"]["llmFallbackWouldMutateOrder"] is True
    assert "已加入" not in result["response"]
    trace_text = json.dumps(result["trace"], ensure_ascii=False)
    assert "13800000000" not in trace_text
    assert "示例大学一号楼" not in trace_text
    assert orchestrator.llm_client.network_allowed is False


def test_shadow_records_validation_rejection_without_mutation():
    payload = json.loads((FIXTURES / "invalid_fabricated_item.json").read_text(encoding="utf-8"))
    orchestrator = OrchestratorAgent()
    orchestrator.llm_client = ShadowLLMClient(InMemoryFakeLLMClient(payload))
    orchestrator.semantic_router.interpret = lambda _message: Interpretation(
        intent="fallback", confidence=0.2, source="deterministic", should_mutate_order=False
    )

    result = orchestrator.handle_user_message("order 虚构套餐 please", SessionState())

    assert result["state"]["current_order"] == []
    assert result["trace"]["llmFallbackValidationRejected"] is True
    assert result["trace"]["llmFallbackValidationRejectReason"] == "menu_item_not_found"
    assert result["trace"]["llmFallbackWouldMutateOrder"] is False
