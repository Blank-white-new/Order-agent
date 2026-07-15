from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.voice.asr.vosk_asr import VoskModelManager
from app.voice.config import clear_settings_cache, get_voice_settings, parse_bool
from app.voice.runtime import create_voice_runtime
from app.voice.status import evaluate_voice_status


EXPECTED_STATUS_KEYS = {
    "voiceEnabled",
    "asrEngine",
    "ttsEnabled",
    "ttsEngine",
    "ttsPlaybackTarget",
    "ttsEngineRecreatePerTask",
    "ttsStyle",
    "ttsProvider",
    "ttsRate",
    "ttsVolume",
    "ttsConfiguredPitch",
    "ttsAppliedPitch",
    "ttsLang",
    "ttsConfiguredVoice",
    "ttsProviderCapabilities",
    "ttsUnsupportedParams",
    "asrReady",
    "ttsReady",
    "asrDependencyAvailable",
    "ttsDependencyAvailable",
    "modelPathExists",
    "modelLooksValid",
    "modelLoaded",
    "canRecord",
    "canSpeak",
    "disabledReason",
    "asrDisabledReason",
    "ttsDisabledReason",
    "hints",
    "envFilePath",
    "envFileExists",
    "voskModelPath",
}


def test_parse_bool_variants():
    for value in ["true", "True", "TRUE", "1", "yes", "on"]:
        assert parse_bool(value) is True
    for value in ["false", "False", "FALSE", "0", "no", "off", "", None, "banana"]:
        assert parse_bool(value) is False


def test_backend_env_file_is_loaded_without_overriding_system_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("VOICE_ENABLED=true\nTTS_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setenv("BACKEND_ENV_FILE", str(env_file))
    monkeypatch.setenv("VOICE_ENABLED", "false")
    monkeypatch.delenv("TTS_ENABLED", raising=False)
    clear_settings_cache()

    settings = get_voice_settings()

    assert settings.voice_enabled is False
    assert settings.tts_enabled is False
    assert settings.env_file_path == str(env_file)
    assert settings.env_file_exists is True


def test_missing_backend_env_file_is_diagnostic(monkeypatch, tmp_path):
    missing = tmp_path / "missing.env"
    monkeypatch.setenv("BACKEND_ENV_FILE", str(missing))
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    clear_settings_cache()

    settings = get_voice_settings()
    status = evaluate_voice_status(settings)

    assert settings.env_file_path == str(missing)
    assert settings.env_file_exists is False
    assert any(str(missing) in hint for hint in status["hints"])


def test_voice_status_disabled_safe(monkeypatch):
    import app.api.voice as voice_api

    monkeypatch.setenv("VOICE_ENABLED", "false")
    clear_settings_cache()
    voice_api.reset_voice_runtime_for_test(create_voice_runtime(get_voice_settings()))
    client = TestClient(app)

    response = client.get("/api/voice/status")

    assert response.status_code == 200
    body = response.json()
    assert EXPECTED_STATUS_KEYS <= set(body)
    assert body["voiceEnabled"] is False
    assert body["canRecord"] is False
    assert body["disabledReason"] == "后端语音未开启"
    assert body["hints"]


def test_status_missing_model_path(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOSK_MODEL_PATH", str(tmp_path / "missing-model"))
    clear_settings_cache()

    status = evaluate_voice_status()

    assert EXPECTED_STATUS_KEYS <= set(status)
    assert status["voiceEnabled"] is True
    assert status["modelPathExists"] is False
    assert status["modelLooksValid"] is False
    assert status["canRecord"] is False
    assert "模型路径不存在" in status["asrDisabledReason"]


def test_status_empty_model_dir_is_not_usable(monkeypatch, tmp_path):
    model_dir = tmp_path / "empty-model"
    model_dir.mkdir()
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOSK_MODEL_PATH", str(model_dir))
    clear_settings_cache()

    status = evaluate_voice_status()

    assert EXPECTED_STATUS_KEYS <= set(status)
    assert status["modelPathExists"] is True
    assert status["modelLooksValid"] is False
    assert status["canRecord"] is False
    assert "模型目录结构无效" in status["asrDisabledReason"]


def test_status_looks_valid_model_can_record_when_dependency_available(monkeypatch, tmp_path):
    model_dir = make_vosk_like_model(tmp_path)
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOSK_MODEL_PATH", str(model_dir))
    clear_settings_cache()

    status = evaluate_voice_status(dependency_probe=lambda name: True)

    assert status["asrDependencyAvailable"] is True
    assert status["modelPathExists"] is True
    assert status["modelLooksValid"] is True
    assert status["canRecord"] is True


def test_dependency_failures_do_not_break_chat(monkeypatch, tmp_path):
    model_dir = make_vosk_like_model(tmp_path)
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("VOSK_MODEL_PATH", str(model_dir))
    clear_settings_cache()

    status = evaluate_voice_status(dependency_probe=lambda name: False)

    assert status["asrDependencyAvailable"] is False
    assert status["ttsDependencyAvailable"] is False
    assert status["canRecord"] is False
    assert status["canSpeak"] is False

    client = TestClient(app)
    response = client.post("/api/chat", json={"session_id": "voice-status-chat", "message": "有啥"})
    assert response.status_code == 200
    assert "饭类" in response.json()["response"]


def test_status_does_not_load_vosk_model(monkeypatch, tmp_path):
    model_dir = make_vosk_like_model(tmp_path)
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOSK_MODEL_PATH", str(model_dir))
    clear_settings_cache()
    before = dict(VoskModelManager._models)

    status = evaluate_voice_status(dependency_probe=lambda name: True)

    assert status["modelLoaded"] is False
    assert VoskModelManager._models == before


# ── TTS style config tests ──


def _use_temp_env(monkeypatch, tmp_path, content: str = "") -> None:
    """Point BACKEND_ENV_FILE to a temp .env with controlled content."""
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    for name in ("VOICE_ENABLED", "TTS_ENABLED", "VOICE_TTS_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BACKEND_ENV_FILE", str(env_file))
    clear_settings_cache()


def _make_config(**overrides: Any):
    """Build a VoiceConfig for testing resolve_effective_tts_params."""
    from app.voice.config import VoiceConfig

    kwargs: dict[str, Any] = {
        "voice_enabled": True,
        "tts_enabled": True,
        "tts_style": "friendly",
        "tts_pitch": 1.05,
        "tts_lang": "zh-CN",
        "tts_provider": "auto",
        "tts_rate": 180,
        "tts_volume": 1.0,
        "tts_voice_name": "",
        "tts_engine": "pyttsx3",
    }
    explicit_vars: set[str] = set()
    for k, v in overrides.items():
        if k == "_explicit_vars":
            explicit_vars = v
        elif k in kwargs:
            kwargs[k] = v
    config = VoiceConfig(**kwargs)
    config._explicit_vars = explicit_vars
    return config


def test_default_style_is_friendly():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config()
    effective = resolve_effective_tts_params(config)
    assert effective["style"] == "friendly"
    assert effective["rate"] == 190


def test_style_friendly_rate_190():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly")
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 190


def test_style_calm_rate_170():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="calm")
    effective = resolve_effective_tts_params(config)
    assert effective["style"] == "calm"
    assert effective["rate"] == 170


def test_style_fast_rate_215():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="fast")
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 215


def test_style_elder_friendly_rate_155():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="elder_friendly")
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 155


def test_style_clear_rate_180():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="clear")
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 180


def test_style_professional_rate_185():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="professional")
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 185


def test_style_cute_rate_195():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="cute")
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 195


def test_calm_slower_than_friendly():
    from app.voice.config import resolve_effective_tts_params

    friendly = resolve_effective_tts_params(_make_config(tts_style="friendly"))
    calm = resolve_effective_tts_params(_make_config(tts_style="calm"))
    assert calm["rate"] < friendly["rate"]


def test_fast_faster_than_friendly():
    from app.voice.config import resolve_effective_tts_params

    friendly = resolve_effective_tts_params(_make_config(tts_style="friendly"))
    fast = resolve_effective_tts_params(_make_config(tts_style="fast"))
    assert fast["rate"] > friendly["rate"]


def test_elder_friendly_much_slower_than_friendly():
    from app.voice.config import resolve_effective_tts_params

    friendly = resolve_effective_tts_params(_make_config(tts_style="friendly"))
    elder = resolve_effective_tts_params(_make_config(tts_style="elder_friendly"))
    diff = friendly["rate"] - elder["rate"]
    assert diff >= 20, f"Expected elder_friendly to be much slower, diff={diff}"


def test_code_default_tts_rate_does_not_override_style_preset():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", tts_rate=180)
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 190, f"Expected style preset rate 190, got {effective['rate']}"


def test_explicit_tts_rate_overrides_style_preset():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", tts_rate=180, _explicit_vars={"TTS_RATE"})
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 180, f"Expected explicit TTS_RATE=180, got {effective['rate']}"


def test_voice_tts_rate_overrides_everything():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", tts_rate=180, _explicit_vars={"VOICE_TTS_RATE", "TTS_RATE"})
    monkeypatch_for_rate = __import__("os").environ.get("VOICE_TTS_RATE", "")
    if not monkeypatch_for_rate:
        import os as _os
        _os.environ["VOICE_TTS_RATE"] = "200"
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 200, f"Expected VOICE_TTS_RATE=200, got {effective['rate']}"


def test_explicit_tts_volume_overrides_style_preset():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", tts_volume=0.5, _explicit_vars={"TTS_VOLUME"})
    effective = resolve_effective_tts_params(config)
    assert effective["volume"] == 0.5


def test_voice_tts_volume_overrides_tts_volume():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", tts_volume=0.5, _explicit_vars={"VOICE_TTS_VOLUME", "TTS_VOLUME"})
    import os as _os2
    _os2.environ["VOICE_TTS_VOLUME"] = "0.8"
    effective = resolve_effective_tts_params(config)
    assert effective["volume"] == 0.8


def test_default_voice_is_empty():
    config = _make_config()
    assert config.tts_voice_name == ""


def test_configured_voice_is_stored():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_voice_name="some-voice-id")
    effective = resolve_effective_tts_params(config)
    assert effective["configuredVoice"] == "some-voice-id"


def test_pitch_configured_but_not_applied():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly")
    effective = resolve_effective_tts_params(config)
    assert effective["configuredPitch"] == 1.05
    assert effective["appliedPitch"] is None


def test_provider_capabilities_pitch_false():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config()
    effective = resolve_effective_tts_params(config)
    assert effective["providerCapabilities"]["pitch"] is False
    assert effective["providerCapabilities"]["rate"] is True
    assert effective["providerCapabilities"]["volume"] is True
    assert effective["providerCapabilities"]["voice"] is True


def test_unsupported_params_contains_pitch():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config()
    effective = resolve_effective_tts_params(config)
    assert "pitch" in effective["unsupportedParams"]


def test_default_provider_is_pyttsx3():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config()
    effective = resolve_effective_tts_params(config)
    assert effective["resolvedProvider"] == "pyttsx3"


def test_provider_auto_resolves_to_pyttsx3():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_provider="auto")
    effective = resolve_effective_tts_params(config)
    assert effective["resolvedProvider"] == "pyttsx3"


def test_provider_pyttsx3_explicit():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_provider="pyttsx3")
    effective = resolve_effective_tts_params(config)
    assert effective["resolvedProvider"] == "pyttsx3"
    assert effective["providerFallbackReason"] is None


def test_provider_edge_tts_fallback_no_crash():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_provider="edge_tts")
    effective = resolve_effective_tts_params(config)
    assert effective["requestedProvider"] == "edge_tts"
    assert effective["resolvedProvider"] == "pyttsx3"
    assert effective["providerFallbackReason"] == "unsupported_provider_requested"


def test_provider_cloud_fallback_no_crash():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_provider="cloud")
    effective = resolve_effective_tts_params(config)
    assert effective["requestedProvider"] == "cloud"
    assert effective["resolvedProvider"] == "pyttsx3"
    assert effective["providerFallbackReason"] == "unsupported_provider_requested"


def test_requested_and_resolved_provider_fields_present():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config()
    effective = resolve_effective_tts_params(config)
    assert "requestedProvider" in effective
    assert "resolvedProvider" in effective
    assert effective["requestedProvider"] == "auto"


def test_unknown_style_fallback_to_friendly():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="nonexistent_style")
    effective = resolve_effective_tts_params(config)
    assert effective["style"] == "friendly"
    assert effective["rate"] == 190


def test_rate_below_80_clamped():
    from app.voice.config import resolve_effective_tts_params, _clamp_rate
    import os as _os5

    assert _clamp_rate(50) == 80
    _os5.environ["VOICE_TTS_RATE"] = "50"
    config = _make_config(tts_style="friendly", tts_rate=50, _explicit_vars={"VOICE_TTS_RATE"})
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 80


def test_rate_above_260_clamped():
    from app.voice.config import resolve_effective_tts_params, _clamp_rate
    import os as _os6

    assert _clamp_rate(300) == 260
    _os6.environ["VOICE_TTS_RATE"] = "300"
    config = _make_config(tts_style="friendly", tts_rate=300, _explicit_vars={"VOICE_TTS_RATE"})
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 260


def test_volume_below_0_clamped():
    from app.voice.config import resolve_effective_tts_params, _clamp_volume
    import os as _os7

    assert _clamp_volume(-0.5) == 0.0
    _os7.environ["VOICE_TTS_VOLUME"] = "-0.5"
    config = _make_config(tts_style="friendly", tts_volume=-0.5, _explicit_vars={"VOICE_TTS_VOLUME"})
    effective = resolve_effective_tts_params(config)
    assert effective["volume"] == 0.0


def test_volume_above_1_clamped():
    from app.voice.config import resolve_effective_tts_params, _clamp_volume
    import os as _os8

    assert _clamp_volume(1.5) == 1.0
    _os8.environ["VOICE_TTS_VOLUME"] = "1.5"
    config = _make_config(tts_style="friendly", tts_volume=1.5, _explicit_vars={"VOICE_TTS_VOLUME"})
    effective = resolve_effective_tts_params(config)
    assert effective["volume"] == 1.0


def test_pitch_clamped():
    from app.voice.config import _clamp_pitch

    assert _clamp_pitch(0.1) == 0.5
    assert _clamp_pitch(3.0) == 2.0
    assert _clamp_pitch(1.0) == 1.0


def test_invalid_rate_string_uses_preset():
    from app.voice.config import resolve_effective_tts_params
    import os as _os3

    _os3.environ["VOICE_TTS_RATE"] = "not_a_number"
    config = _make_config(tts_style="friendly", _explicit_vars={"VOICE_TTS_RATE"})
    effective = resolve_effective_tts_params(config)
    assert effective["rate"] == 190


def test_invalid_volume_string_uses_preset():
    from app.voice.config import resolve_effective_tts_params
    import os as _os4

    _os4.environ["VOICE_TTS_VOLUME"] = "not_a_number"
    config = _make_config(tts_style="friendly", _explicit_vars={"VOICE_TTS_VOLUME"})
    effective = resolve_effective_tts_params(config)
    assert effective["volume"] == 1.0


def test_legacy_config_used_when_old_vars_set():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", _explicit_vars={"TTS_RATE"})
    effective = resolve_effective_tts_params(config)
    assert effective["legacyConfigUsed"] is True


def test_legacy_config_not_used_when_only_new_vars():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_style="friendly", _explicit_vars={"VOICE_TTS_STYLE"})
    effective = resolve_effective_tts_params(config)
    assert effective["legacyConfigUsed"] is False


def test_tts_enabled_false_disables_tts():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_enabled=False)
    effective = resolve_effective_tts_params(config)
    assert effective["enabled"] is False


def test_tts_enabled_false_old_var():
    from app.voice.config import resolve_effective_tts_params

    config = _make_config(tts_enabled=False, _explicit_vars={"TTS_ENABLED"})
    effective = resolve_effective_tts_params(config)
    assert effective["enabled"] is False


def test_status_endpoint_does_not_create_runner(monkeypatch, tmp_path):
    import app.api.voice as voice_api
    from app.voice.runtime import create_voice_runtime

    _use_temp_env(monkeypatch, tmp_path, "VOICE_ENABLED=true\nVOICE_TTS_STYLE=friendly\n")
    clear_settings_cache()
    config = get_voice_settings()
    runtime = create_voice_runtime(config)
    voice_api.reset_voice_runtime_for_test(runtime)

    assert runtime._tts_runner is None, "Runner should not exist before status call"

    client = TestClient(app)
    response = client.get("/api/voice/tts/status")

    assert response.status_code == 200
    assert runtime._tts_runner is None, "Status endpoint must NOT create a TTS runner"
    body = response.json()
    assert body["queueInitialized"] is False
    assert body["speaking"] is False


def test_status_endpoint_returns_style_config_fields(monkeypatch, tmp_path):
    import app.api.voice as voice_api
    from app.voice.runtime import create_voice_runtime

    _use_temp_env(monkeypatch, tmp_path, "VOICE_ENABLED=true\nVOICE_TTS_STYLE=friendly\n")
    clear_settings_cache()
    config = get_voice_settings()
    runtime = create_voice_runtime(config)
    voice_api.reset_voice_runtime_for_test(runtime)

    client = TestClient(app)
    response = client.get("/api/voice/tts/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["style"] == "friendly"
    assert body["provider"] == "pyttsx3"
    assert body["configuredPitch"] == 1.05
    assert body["appliedPitch"] is None
    assert body["providerCapabilities"]["pitch"] is False
    assert "pitch" in body["unsupportedParams"]
    assert body["updatedAt"] is not None
    assert body["queueInitialized"] is False


def test_evaluate_voice_status_includes_style_fields(monkeypatch, tmp_path):
    _use_temp_env(monkeypatch, tmp_path, "VOICE_TTS_STYLE=calm\nVOICE_ENABLED=true\n")
    clear_settings_cache()

    status = evaluate_voice_status()
    assert status["ttsStyle"] == "calm"
    assert status["ttsVolume"] == 1.0
    assert status["ttsConfiguredPitch"] == 0.98
    assert status["ttsAppliedPitch"] is None
    assert status["ttsLang"] == "zh-CN"
    assert status["ttsProviderCapabilities"]["pitch"] is False
    assert "pitch" in status["ttsUnsupportedParams"]


def test_chat_still_works_after_tts_config_changes(monkeypatch, tmp_path):
    import app.api.voice as voice_api
    from app.voice.runtime import create_voice_runtime

    _use_temp_env(monkeypatch, tmp_path, "VOICE_ENABLED=true\nVOICE_TTS_STYLE=fast\n")
    clear_settings_cache()
    config = get_voice_settings()
    runtime = create_voice_runtime(config)
    voice_api.reset_voice_runtime_for_test(runtime)

    client = TestClient(app)
    response = client.post("/api/chat", json={"session_id": "tts-config-chat", "message": "有啥吃的"})
    assert response.status_code == 200
    assert "饭" in response.json()["response"] or "菜" in response.json()["response"]


def make_vosk_like_model(tmp_path: Path) -> Path:
    model_dir = tmp_path / "vosk-cn"
    (model_dir / "conf").mkdir(parents=True)
    (model_dir / "am").mkdir()
    (model_dir / "graph").mkdir()
    (model_dir / "conf" / "model.conf").write_text("fake", encoding="utf-8")
    return model_dir
