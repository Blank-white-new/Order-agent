from __future__ import annotations

import asyncio
import difflib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.text_entry_service import TextEntryService
from app.voice.asr.base import ASRProvider
from app.voice.asr.vosk_asr import VoskASRProvider
from app.voice.config import VoiceConfig
from app.voice.debug import log_auto_tts_debug, preview_text
from app.voice.session import VoiceSessionController
from app.voice.text_cleaner import clean_text_for_tts, is_empty_transcript, normalize_voice_transcript
from app.voice.transcript_normalizer import normalize_ordering_voice_transcript
from app.voice.tts.base import TTSProvider
from app.voice.runtime import VoiceRuntime, create_voice_runtime


EmitCallback = Callable[[dict[str, Any]], Awaitable[None]]
logger = logging.getLogger(__name__)


class VoiceGatewayAgent:
    name = "VoiceGatewayAgent"
    role = "io_gateway"
    can_mutate_order = False
    can_call_business_tools = False

    def __init__(
        self,
        text_entry_service: TextEntryService,
        session_controller: VoiceSessionController | None = None,
        config: VoiceConfig | None = None,
        asr_provider_factory: Callable[[], ASRProvider] | None = None,
        tts_provider: TTSProvider | None = None,
        runtime: VoiceRuntime | None = None,
    ) -> None:
        self.text_entry_service = text_entry_service
        self.session_controller = session_controller or VoiceSessionController()
        self.config = config or VoiceConfig.from_env()
        self.asr_provider_factory = asr_provider_factory or (lambda: VoskASRProvider(self.config))
        self.runtime = runtime or create_voice_runtime(self.config, tts_provider_factory=(lambda: tts_provider) if tts_provider is not None else None)

    def start_session(self, session_id: str, tts_enabled: bool | None = None) -> dict[str, Any]:
        session = self.session_controller.get_session(session_id)
        if not self.config.voice_enabled:
            session.set_status("error")
            return {"type": "error", "message": "语音功能未开启，请设置 VOICE_ENABLED=true。"}
        try:
            if session.recognizer is None:
                session.recognizer = self.asr_provider_factory()
                session.recognizer.start()
        except Exception as exc:
            session.set_status("error")
            return {"type": "error", "message": str(exc)}
        session.tts_enabled = bool(tts_enabled) if tts_enabled is not None else False
        session.muted = False
        session.set_status("idle")
        return {"type": "status", "status": "idle", "muted": session.muted}

    def stop_session(self, session_id: str) -> dict[str, Any]:
        self.session_controller.release_session(session_id)
        return {"type": "status", "status": "idle", "muted": False}

    def begin_utterance(self, session_id: str, utterance_id: str, tts_enabled: bool | None = None) -> dict[str, Any]:
        session = self.session_controller.get_session(session_id)
        session.current_utterance_id = utterance_id
        session.tts_enabled = bool(tts_enabled) if tts_enabled is not None else False
        session.muted = False
        session.set_utterance_tts_preference(utterance_id, session.tts_enabled)
        session.set_status("listening")
        self._log_auto_tts_debug(
            "start_utterance.tts_enabled",
            session_id=session_id,
            utterance_id=utterance_id,
            tts_enabled=session.tts_enabled,
            runtimeId=self.runtime.runtime_id,
        )
        self._log_auto_tts_debug(
            "preference_saved",
            session_id=session_id,
            utterance_id=utterance_id,
            tts_enabled=session.tts_enabled,
        )
        return {"type": "status", "status": "listening", "utterance_id": utterance_id, "muted": session.muted}

    async def on_audio_chunk(self, session_id: str, chunk: bytes) -> list[dict[str, Any]]:
        session = self.session_controller.get_session(session_id)
        if not session.recognizer:
            started = self.start_session(session_id)
            if started.get("type") == "error":
                return [started]
        session.set_status("recognizing")
        session.recognizer.accept_audio_chunk(chunk)
        partial = session.recognizer.get_partial_transcript()
        return [self.on_partial_transcript(session_id, partial)] if partial else []

    def on_partial_transcript(self, session_id: str, text: str) -> dict[str, Any]:
        return {"type": "partial", "text": text}

    async def stop_utterance(self, session_id: str, utterance_id: str, emit: EmitCallback | None = None) -> list[dict[str, Any]]:
        session = self.session_controller.get_session(session_id)
        if not utterance_id:
            utterance_id = session.current_utterance_id or ""
            logger.warning("voice stop_utterance missing utterance_id, using active=%s", utterance_id)
        if session.current_utterance_id and utterance_id != session.current_utterance_id:
            self._log_auto_tts_debug(
                "stop_utterance_mismatch",
                session_id=session_id,
                active_utterance_id=session.current_utterance_id,
                utterance_id=utterance_id,
            )
            return [
                {
                    "type": "error",
                    "code": "utterance_id_mismatch",
                    "message": "stop_utterance utterance_id does not match the active utterance.",
                    "utterance_id": utterance_id,
                    "active_utterance_id": session.current_utterance_id,
                }
            ]
        if not session.recognizer:
            return [{"type": "ignored_empty_transcript", "utterance_id": utterance_id, "ignored": True}]
        final = session.recognizer.get_final_transcript()
        return await self.on_final_transcript(session_id, utterance_id, final, emit=emit)

    async def on_final_transcript(
        self,
        session_id: str,
        utterance_id: str,
        text: str,
        emit: EmitCallback | None = None,
    ) -> list[dict[str, Any]]:
        session = self.session_controller.get_session(session_id)
        normalized = normalize_voice_transcript(text)
        self._log_auto_tts_debug(
            "final_text_length",
            session_id=session_id,
            utterance_id=utterance_id,
            textLength=len(normalized),
            preview=preview_text(normalized),
        )
        if is_empty_transcript(normalized):
            session.clear_active_utterance(utterance_id)
            self._log_auto_tts_debug(
                "ignored_empty_transcript",
                session_id=session_id,
                utterance_id=utterance_id,
                tts_enabled=session.get_utterance_tts_preference(utterance_id),
            )
            return [
                {"type": "ignored_empty_transcript", "utterance_id": utterance_id, "ignored": True},
                self._tts_skipped_event(utterance_id, "ignored_empty_transcript", tts_enabled=session.get_utterance_tts_preference(utterance_id)),
            ]
        if self._looks_like_tts_echo(session, utterance_id, normalized):
            session.clear_active_utterance(utterance_id)
            self._log_auto_tts_debug(
                "ignored_tts_echo_transcript",
                session_id=session_id,
                utterance_id=utterance_id,
                tts_enabled=session.get_utterance_tts_preference(utterance_id),
            )
            return [
                {"type": "ignored_empty_transcript", "utterance_id": utterance_id, "ignored": True},
                self._tts_skipped_event(utterance_id, "ignored_empty_transcript", tts_enabled=session.get_utterance_tts_preference(utterance_id)),
            ]
        if session.processed_utterances.has(utterance_id):
            session.clear_active_utterance(utterance_id)
            self._log_auto_tts_debug(
                "duplicate_utterance",
                session_id=session_id,
                utterance_id=utterance_id,
                tts_enabled=session.get_utterance_tts_preference(utterance_id),
            )
            return [
                {"type": "duplicate_utterance", "utterance_id": utterance_id, "ignored": True},
                self._tts_skipped_event(utterance_id, "duplicate_utterance", tts_enabled=session.get_utterance_tts_preference(utterance_id)),
            ]
        session.processed_utterances.add(utterance_id)
        self.stop_tts(session_id)
        session.set_status("thinking")

        normalization = normalize_ordering_voice_transcript(
            normalized,
            menu_items=self._menu_items_for_transcript_normalizer(),
            context=self._transcript_normalizer_context(session_id),
        )
        final_text = normalization.normalized_text
        if normalization.changed:
            self._log_auto_tts_debug(
                "voice_transcript_normalized",
                session_id=session_id,
                utterance_id=utterance_id,
                original_text=normalization.original_text,
                normalized_text=normalization.normalized_text,
                reasons=normalization.reasons,
                corrections=normalization.corrections,
                confidence=normalization.confidence,
            )

        text_result = await self.handle_final_text(session_id, final_text)
        final_event = {"type": "final", "utterance_id": utterance_id, "text": final_text}
        reply_event = {
            "type": "agent_reply",
            "utterance_id": utterance_id,
            "text": text_result["response"],
            "state": text_result["state"],
            "trace": text_result["trace"],
        }
        self._log_auto_tts_debug(
            "agent_reply_length",
            session_id=session_id,
            utterance_id=utterance_id,
            textLength=len(text_result["response"] or ""),
            preview=preview_text(text_result["response"]),
        )
        events = [final_event, reply_event, self._queue_auto_tts(session_id, utterance_id, text_result["response"])]
        session.clear_active_utterance(utterance_id)
        if session.status != "speaking":
            session.set_status("idle")
        return events

    async def handle_final_text(self, session_id: str, text: str) -> dict[str, Any]:
        return await self.text_entry_service.handle_text_message(session_id, text)

    def queue_manual_tts(self, reply_text: str) -> dict[str, Any]:
        return self.runtime.queue_manual_tts(reply_text)

    async def speak_agent_reply(self, session_id: str, reply_text: str, emit: EmitCallback | None = None) -> dict[str, Any] | None:
        result = self._queue_tts(reply_text, source="manual")
        return {"type": "tts_status", "source": "manual", **result}

    def tts_status(self) -> dict[str, Any]:
        return self.runtime.tts_status()

    def stop_tts(self, session_id: str | None = None) -> dict[str, Any]:
        result = self.runtime.stop_tts()
        if session_id:
            session = self.session_controller.get_session(session_id)
            session.muted = False
            if session.status == "speaking":
                session.set_status("idle")
        return result

    def shutdown_tts(self) -> None:
        self.runtime.shutdown()

    async def wait_for_tts_tasks(self) -> None:
        runner = self.runtime._tts_runner
        if runner is not None:
            await asyncio.to_thread(runner.wait_until_idle)
            return
        await asyncio.sleep(0)

    def _queue_auto_tts(self, session_id: str, utterance_id: str, reply_text: str) -> dict[str, Any]:
        session = self.session_controller.get_session(session_id)
        preference_missing = not session.has_utterance_tts_preference(utterance_id)
        tts_enabled = session.get_utterance_tts_preference(utterance_id)
        self._log_auto_tts_debug(
            "preference_lookup_found",
            session_id=session_id,
            utterance_id=utterance_id,
            preference_found=not preference_missing,
            tts_enabled=tts_enabled,
        )
        if not tts_enabled:
            if preference_missing:
                self._log_auto_tts_debug("preference_missing", session_id=session_id, utterance_id=utterance_id)
            self._log_auto_tts_debug(
                "tts_enabled=false",
                session_id=session_id,
                utterance_id=utterance_id,
                queued=False,
                reason="user_tts_preference_off",
            )
            return self._tts_skipped_event(utterance_id, "user_tts_preference_off", tts_enabled=tts_enabled)

        def on_start() -> None:
            session.muted = True
            session.set_status("speaking")

        def on_finish(success: bool) -> None:
            session.muted = False
            if session.status == "speaking":
                session.set_status("idle")

        cleaned = clean_text_for_tts(reply_text)
        self._log_auto_tts_debug(
            "cleaned_tts_text_length",
            session_id=session_id,
            utterance_id=utterance_id,
            textLength=len(cleaned),
            preview=preview_text(cleaned),
        )
        self._log_auto_tts_debug(
            "queue_tts_called",
            session_id=session_id,
            utterance_id=utterance_id,
            source="auto",
            runtimeId=self.runtime.runtime_id,
        )
        result = self._queue_tts(reply_text, source="auto", on_start=on_start, on_finish=on_finish)
        self._log_auto_tts_debug(
            "queue_tts_result",
            session_id=session_id,
            utterance_id=utterance_id,
            source="auto",
            runtimeId=self.runtime.runtime_id,
            runnerId=id(self.runtime._tts_runner) if self.runtime._tts_runner is not None else None,
            queued=result.get("queued"),
            reason=result.get("reason"),
            job_id=result.get("job_id"),
        )
        if result.get("queued") and result.get("job_id") is not None:
            runner_id = self.runtime.tts_status().get("runnerId")
            self._log_auto_tts_debug(
                "queue_tts_result",
                session_id=session_id,
                utterance_id=utterance_id,
                source="auto",
                runtimeId=self.runtime.runtime_id,
                runnerId=runner_id,
                queued=True,
                job_id=result.get("job_id"),
            )
            return {
                "type": "tts_status",
                "utterance_id": utterance_id,
                "source": "auto",
                "tts_enabled": tts_enabled,
                **result,
            }
        self._log_auto_tts_debug(
            str(result.get("reason", "tts_error")),
            session_id=session_id,
            utterance_id=utterance_id,
            tts_enabled=tts_enabled,
            queued=False,
            reason=result.get("reason", "tts_error"),
            job_id=None,
        )
        return self._tts_skipped_event(utterance_id, result.get("reason", "tts_error"), tts_enabled=tts_enabled)

    def _log_auto_tts_debug(self, event: str, **fields: Any) -> None:
        log_auto_tts_debug(
            logger,
            self.config,
            event,
            **fields,
        )

    def _menu_items_for_transcript_normalizer(self) -> list[str]:
        menu_service = getattr(getattr(self.text_entry_service, "orchestrator", None), "menu_service", None)
        if menu_service is None:
            try:
                from app.services.menu_service import MenuService

                menu_service = MenuService()
            except Exception:
                return []
        try:
            items = menu_service.all_items_as_dicts()
        except Exception:
            return []
        menu_items: list[str] = []
        for item in items:
            name = item.get("name")
            if name:
                menu_items.append(name)
            aliases = item.get("aliases") or []
            menu_items.extend(alias for alias in aliases if alias)
        return menu_items

    def _transcript_normalizer_context(self, session_id: str) -> dict[str, Any]:
        store = getattr(self.text_entry_service, "store", None)
        if store is None:
            return {}
        try:
            state = store.get(session_id)
        except Exception:
            return {}
        current_order = getattr(state, "current_order", []) or []
        return {
            "stage": getattr(state, "stage", None),
            "fulfillment_type": getattr(state, "fulfillment_type", None),
            "pending_question": getattr(state, "pending_question", None),
            "last_question_intent": getattr(state, "last_question_intent", None),
            "current_order_count": len(current_order),
            "last_mentioned_item": getattr(state, "last_mentioned_item", None),
            "last_mentioned_category": getattr(state, "last_mentioned_category", None),
            "viewed_category": getattr(state, "viewed_category", None),
            "viewed_category_group": getattr(state, "viewed_category_group", None),
        }

    def _queue_tts(
        self,
        reply_text: str,
        *,
        source: str,
        on_start: Callable[[], None] | None = None,
        on_finish: Callable[[bool], None] | None = None,
    ) -> dict[str, Any]:
        return self.runtime.queue_tts(reply_text, source=source, on_start=on_start, on_finish=on_finish)

    def _tts_skipped_event(self, utterance_id: str, reason: str, *, tts_enabled: bool | None = None) -> dict[str, Any]:
        if reason not in {
            "user_tts_preference_off",
            "tts_disabled",
            "can_speak_false",
            "empty_text",
            "tts_queue_full",
            "tts_queue_stuck",
            "runner_shutdown",
            "duplicate_utterance",
            "ignored_empty_transcript",
            "tts_error",
        }:
            reason = "tts_error"
        return {
            "type": "tts_status",
            "utterance_id": utterance_id,
            "source": "auto",
            "queued": False,
            "reason": reason,
            "job_id": None,
            "tts_enabled": bool(tts_enabled),
        }

    def _looks_like_tts_echo(self, session: Any, utterance_id: str, normalized: str) -> bool:
        if utterance_id and session.current_utterance_id == utterance_id:
            return False
        recent_text, started_at = self.runtime.recent_tts_text_snapshot()
        if not recent_text or started_at is None:
            return False
        if time.monotonic() - started_at > 2.0:
            return False
        return _texts_are_highly_similar(normalized, recent_text)


def _compact_for_echo_compare(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _texts_are_highly_similar(left: str, right: str) -> bool:
    compact_left = _compact_for_echo_compare(left)
    compact_right = _compact_for_echo_compare(right)
    if not compact_left or not compact_right:
        return False
    if compact_left == compact_right:
        return True
    shorter, longer = sorted((compact_left, compact_right), key=len)
    if len(shorter) >= 8 and shorter in longer and len(shorter) / len(longer) >= 0.9:
        return True
    if min(len(compact_left), len(compact_right)) < 8:
        return False
    return difflib.SequenceMatcher(a=compact_left, b=compact_right).ratio() >= 0.92
