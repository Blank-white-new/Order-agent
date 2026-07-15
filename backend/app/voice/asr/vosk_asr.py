from __future__ import annotations

import json
import ntpath
import os
from pathlib import Path
from typing import Any

from app.voice.asr.base import ASRProvider
from app.voice.config import VoiceConfig


class VoskModelManager:
    _models: dict[str, Any] = {}

    @classmethod
    def model_exists(cls, model_path: str) -> bool:
        return Path(model_path).exists()

    @classmethod
    def get_model(cls, model_path: str) -> Any:
        if not cls.model_exists(model_path):
            raise FileNotFoundError(f"未找到 Vosk 模型，请检查 VOSK_MODEL_PATH: {model_path}")
        if model_path not in cls._models:
            try:
                from vosk import Model
            except ImportError as exc:
                raise RuntimeError("未安装 vosk，请先安装后端语音依赖。") from exc
            cls._models[model_path] = Model(_native_vosk_model_path(model_path))
        return cls._models[model_path]


class VoskASRProvider(ASRProvider):
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.recognizer: Any = None
        self._partial = ""
        self._final = ""

    def start(self) -> None:
        try:
            from vosk import KaldiRecognizer
        except ImportError as exc:
            raise RuntimeError("未安装 vosk，请先安装后端语音依赖。") from exc
        model = VoskModelManager.get_model(self.config.vosk_model_path)
        self.recognizer = KaldiRecognizer(model, self.config.asr_sample_rate)
        self._partial = ""
        self._final = ""

    def stop(self) -> None:
        self.recognizer = None

    def accept_audio_chunk(self, chunk: bytes) -> None:
        if not self.recognizer:
            self.start()
        if self.recognizer.AcceptWaveform(chunk):
            payload = _safe_json_loads(self.recognizer.Result())
            self._final = str(payload.get("text", "")).strip()
        else:
            payload = _safe_json_loads(self.recognizer.PartialResult())
            self._partial = str(payload.get("partial", "")).strip()

    def get_partial_transcript(self) -> str:
        return self._partial

    def get_final_transcript(self) -> str:
        if self._final:
            final = self._final
            self._final = ""
            return final
        if not self.recognizer:
            return ""
        payload = _safe_json_loads(self.recognizer.FinalResult())
        return str(payload.get("text", "")).strip()

    def reset(self) -> None:
        self.stop()
        self.start()


def _safe_json_loads(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _native_vosk_model_path(
    model_path: str,
    *,
    current_dir: str | Path | None = None,
    platform_name: str | None = None,
) -> str:
    """Avoid Vosk's Windows native-path encoding issue when a parent directory is non-ASCII."""
    if (platform_name or os.name) != "nt" or model_path.isascii():
        return model_path

    start = str(current_dir or Path.cwd())
    try:
        relative_path = ntpath.relpath(model_path, start=start)
    except ValueError:
        return model_path
    return relative_path if relative_path.isascii() else model_path
