from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from app.voice.asr import vosk_asr
from app.voice.asr.vosk_asr import VoskModelManager, _native_vosk_model_path


def test_windows_native_model_path_uses_ascii_relative_path() -> None:
    model_path = r"C:\Users\用户\repo\models\asr\vosk-cn"
    current_dir = r"C:\Users\用户\repo\backend"

    native_path = _native_vosk_model_path(
        model_path,
        current_dir=current_dir,
        platform_name="nt",
    )

    assert native_path == r"..\models\asr\vosk-cn"
    assert native_path.isascii()


def test_native_model_path_is_unchanged_off_windows() -> None:
    model_path = "/home/用户/repo/models/asr/vosk-cn"

    assert _native_vosk_model_path(model_path, platform_name="posix") == model_path


def test_model_manager_passes_native_safe_path_to_vosk(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    calls: list[str] = []
    fake_vosk = ModuleType("vosk")

    class FakeModel:
        def __init__(self, path: str) -> None:
            calls.append(path)

    fake_vosk.Model = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vosk", fake_vosk)
    monkeypatch.setattr(vosk_asr, "_native_vosk_model_path", lambda _path: "models\\asr\\vosk-cn")
    VoskModelManager._models.clear()

    try:
        VoskModelManager.get_model(str(model_dir))
    finally:
        VoskModelManager._models.clear()

    assert calls == [r"models\asr\vosk-cn"]
