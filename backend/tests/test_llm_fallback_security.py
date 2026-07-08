from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.llm_fallback_prompt import build_llm_fallback_prompt
from app.services.menu_service import MenuService
from app.state.session_state import SessionState


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_prompt_sanitizes_phone_and_address_in_current_message():
    prompt = build_llm_fallback_prompt(
        "请处理13812345678送到中山大学南校园这个",
        SessionState(),
        MenuService(),
    )

    assert "13812345678" not in prompt
    assert "中山大学南校园" not in prompt
    assert "address_present" in prompt
    assert "phone_present" in prompt


def test_prompt_does_not_include_full_state_phone_or_address_by_default():
    state = SessionState(official_delivery_address="中山大学南校园", phone="13812345678")

    prompt = build_llm_fallback_prompt("随便处理一下", state, MenuService())

    assert "13812345678" not in prompt
    assert "中山大学南校园" not in prompt
    assert '"address_present":true' in prompt
    assert '"phone_present":true' in prompt


@pytest.mark.parametrize(
    "phone",
    [
        "13800000000",
        "138-0000-0000",
        "138 0000 0000",
        "138 0000-0000",
        "138-0000 0000",
    ],
)
def test_prompt_redacts_common_phone_variants(phone):
    prompt = build_llm_fallback_prompt(f"电话是{phone}，帮我处理一下", SessionState(), MenuService())
    context = json.loads(prompt)

    assert phone not in prompt
    assert "[phone hidden]" in context["current_user_input"]


@pytest.mark.parametrize(
    "message",
    [
        "送到珠江新城帮我处理",
        "送到中山大学南校园",
        "地址是中山大学南校园",
        "我在宿舍楼下",
    ],
)
def test_prompt_hides_obvious_address_messages(message):
    prompt = build_llm_fallback_prompt(message, SessionState(), MenuService())
    context = json.loads(prompt)

    assert message not in prompt
    assert context["current_user_input"] == "[address-related message hidden]"
    assert context["input_is_address_like"] is True


def test_real_env_files_are_not_tracked_by_git():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tracked = set(result.stdout.splitlines())

    assert ".env.example" in tracked
    assert ".env" not in tracked
    assert ".env.local" not in tracked
    assert not any(path.endswith(".env") and path != ".env.example" for path in tracked)
    assert not any(Path(path).name.startswith(".env.") and path != ".env.example" for path in tracked)


def test_env_example_uses_placeholders_only():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert re.search(r"sk-[A-Za-z0-9]{10,}", example) is None
    assert "LLM_FALLBACK_ENABLED=false" in example
    assert "LLM_FALLBACK_API_KEY=" in example


def test_gitignore_covers_env_variants_and_keeps_example_trackable():
    patterns = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env.*" in patterns
    assert patterns.index("!.env.example") > patterns.index(".env.*")


def test_check_scripts_enable_shared_offline_llm_guard():
    guard = (PROJECT_ROOT / "scripts" / "offline_llm_guard.ps1").read_text(encoding="utf-8")
    for script_name in ["check_all.ps1", "check_backend.ps1"]:
        script = (PROJECT_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert 'offline_llm_guard.ps1' in script
        assert "Enable-OfflineLlmChecks" in script
        assert "Restore-LlmCheckEnvironment" in script

    assert 'SetEnvironmentVariable("LLM_FALLBACK_ENABLED", "false"' in guard
    assert 'SetEnvironmentVariable("BACKEND_ENV_FILE", $offlineEnvFile' in guard
    assert '"LLM_FALLBACK_API_KEY"' in guard
    assert '"DEEPSEEK_API_KEY"' in guard
    assert "live provider configuration is isolated" in guard


def test_conftest_overrides_live_like_parent_environment_before_app_import():
    probe = r'''
import os
from tests import conftest  # noqa: F401
from app.services.llm_client import LLMClient

class NetworkBlocker:
    def __init__(self):
        self.calls = 0
    def post(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("network must not be called")

assert os.environ["LLM_FALLBACK_ENABLED"] == "false"
assert "LLM_FALLBACK_API_KEY" not in os.environ
assert "DEEPSEEK_API_KEY" not in os.environ
assert not os.path.exists(os.environ["BACKEND_ENV_FILE"])
blocker = NetworkBlocker()
client = LLMClient(http_client=blocker)
assert client.is_enabled() is False
assert client.is_configured() is False
assert client.can_call() is False
assert client.interpret("offline probe").status == "disabled"
assert blocker.calls == 0
'''
    env = os.environ.copy()
    env.update(
        {
            "LLM_FALLBACK_ENABLED": "true",
            "LLM_FALLBACK_API_KEY": "fake-but-present",
            "LLM_FALLBACK_BASE_URL": "https://example.invalid",
            "LLM_FALLBACK_MODEL": "fake-model",
            "DEEPSEEK_API_KEY": "fake-legacy-key",
        }
    )

    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=PROJECT_ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
