from __future__ import annotations

import uuid
import logging
from collections.abc import Callable
from typing import Any

from app.voice.config import VoiceConfig
from app.voice.debug import log_auto_tts_debug, preview_text
from app.voice.status import evaluate_voice_status
from app.voice.text_cleaner import clean_text_for_tts
from app.voice.tts.base import TTSProvider
from app.voice.tts.pyttsx3_tts import Pyttsx3TTSProvider
from app.voice.tts.runner import AsyncTTSRunner, default_tts_status


TTS_SKIP_REASONS = {
    "user_tts_preference_off",
    "tts_disabled",
    "can_speak_false",
    "empty_text",
    "tts_queue_full",
    "tts_queue_stuck",
    "runner_shutdown",
    "tts_error",
}

logger = logging.getLogger(__name__)


class VoiceRuntime:
    def __init__(
        self,
        config: VoiceConfig,
        tts_provider_factory: Callable[[], TTSProvider] | None = None,
    ) -> None:
        self.config = config
        self.runtime_id = f"voice-runtime-{uuid.uuid4().hex[:8]}"
        self._tts_provider_factory = tts_provider_factory or (lambda: Pyttsx3TTSProvider(config))
        self._tts_runner: AsyncTTSRunner | None = None

    def queue_tts(
        self,
        reply_text: str,
        *,
        source: str,
        on_start: Callable[[], None] | None = None,
        on_finish: Callable[[bool], None] | None = None,
    ) -> dict[str, Any]:
        playback_target = self.config.tts_playback_target
        if not self.config.tts_enabled:
            self._log_auto_tts_debug("tts_disabled", source=source, runtimeId=self.runtime_id)
            return self._queue_result(False, source=source, reason="tts_disabled", playback_target=playback_target)
        status = evaluate_voice_status(self.config)
        if not status.get("ttsReady"):
            self._log_auto_tts_debug("can_speak_false", source=source, runtimeId=self.runtime_id)
            return self._queue_result(False, source=source, reason="can_speak_false", playback_target=playback_target)
        if reply_text is None or reply_text == "":
            self._log_auto_tts_debug("agent_reply_empty", source=source, runtimeId=self.runtime_id)
            return self._queue_result(False, source=source, reason="empty_text", playback_target=playback_target)
        cleaned = clean_text_for_tts(reply_text)
        self._log_auto_tts_debug(
            "cleaned_tts_text_length",
            source=source,
            runtimeId=self.runtime_id,
            textLength=len(cleaned),
            preview=preview_text(cleaned),
        )
        if not cleaned:
            self._log_auto_tts_debug("cleaned_tts_text_empty", source=source, runtimeId=self.runtime_id)
            return self._queue_result(False, source=source, reason="empty_text", playback_target=playback_target)
        try:
            runner = self.get_tts_runner()
            enqueue_result = runner.enqueue(
                cleaned,
                source=source,  # type: ignore[arg-type]
                on_start=on_start,
                on_finish=on_finish,
            )
        except Exception as exc:
            logger.exception("voice tts enqueue error: runtime_id=%s, source=%s", self.runtime_id, source)
            return self._queue_result(False, source=source, reason="tts_error", playback_target=playback_target)
        if enqueue_result.get("queued"):
            job_id = enqueue_result.get("job_id")
            self._log_auto_tts_debug(
                "queue_tts_result",
                source=source,
                runtimeId=self.runtime_id,
                runnerId=id(self._tts_runner) if self._tts_runner is not None else None,
                queued=True,
                job_id=job_id,
            )
            return self._queue_result(True, source=source, job_id=job_id, playback_target=playback_target)
        reason = enqueue_result.get("error", "tts_error")
        if reason not in TTS_SKIP_REASONS:
            reason = "tts_error"
        return self._queue_result(False, source=source, reason=reason, playback_target=playback_target)

    def queue_manual_tts(self, text: str) -> dict[str, Any]:
        result = self.queue_tts(text, source="manual")
        if result.get("queued"):
            return result
        if result.get("reason") == "empty_text":
            result["ignored"] = True
            result["error"] = "ignored_empty_tts_text"
            return result
        result["error"] = result.get("reason", "tts_error")
        return result

    def tts_status(self) -> dict[str, Any]:
        if self._tts_runner is None:
            status = default_tts_status(self.config)
        else:
            status = self._tts_runner.status()
        status["runtimeId"] = self.runtime_id
        status["runnerId"] = id(self._tts_runner) if self._tts_runner is not None else None
        return status

    def get_tts_runner(self) -> AsyncTTSRunner:
        if self._tts_runner is None:
            self._tts_runner = AsyncTTSRunner(self._tts_provider_factory, self.config)
            logger.debug("voice tts runner created: runtime_id=%s, runner_id=%s", self.runtime_id, id(self._tts_runner))
        return self._tts_runner

    def shutdown(self) -> None:
        if self._tts_runner is not None:
            self._tts_runner.shutdown()

    def _queue_result(
        self,
        queued: bool,
        *,
        source: str,
        playback_target: str,
        job_id: Any = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if reason is not None and reason not in TTS_SKIP_REASONS:
            reason = "tts_error"
        return {
            "ok": queued,
            "queued": queued,
            "job_id": job_id if queued else None,
            "source": source,
            "reason": None if queued else (reason or "tts_error"),
            "playbackTarget": playback_target,
        }

    def _log_auto_tts_debug(self, event: str, **fields: Any) -> None:
        if fields.get("source") != "auto":
            return
        log_auto_tts_debug(logger, self.config, event, **fields)


def create_voice_runtime(
    config: VoiceConfig | None = None,
    tts_provider_factory: Callable[[], TTSProvider] | None = None,
) -> VoiceRuntime:
    return VoiceRuntime(config or VoiceConfig.from_env(), tts_provider_factory=tts_provider_factory)
