from __future__ import annotations

import queue
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.voice.config import VoiceConfig
from app.voice.tts.base import TTSProvider


TTSSource = Literal["auto", "manual"]
logger = logging.getLogger(__name__)


@dataclass
class TTSJob:
    job_id: int
    text: str
    source: TTSSource
    queued_at: float
    queued_at_iso: str
    preview: str
    on_start: Callable[[], None] | None = None
    on_finish: Callable[[bool], None] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize_error(exc: BaseException) -> str:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > 180:
        message = f"{message[:177]}..."
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


class AsyncTTSRunner:
    def __init__(
        self,
        provider_factory: Callable[[], TTSProvider],
        config: VoiceConfig,
        max_queue_size: int = 10,
        stuck_threshold_seconds: int = 30,
    ) -> None:
        self.provider_factory = provider_factory
        self.config = config
        self.max_queue_size = max_queue_size
        self.stuck_threshold_seconds = stuck_threshold_seconds
        self._queue: queue.Queue[TTSJob] = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._provider: TTSProvider | None = None
        self._queue_initialized = False
        self._stopped = False
        self._speaking = False
        self._next_job_id = 0
        self._worker_restart_count = 0
        self._jobs_queued = 0
        self._jobs_started = 0
        self._jobs_finished = 0
        self._total_successes = 0
        self._total_failures = 0
        self._last_queued_at: str | None = None
        self._last_started_at: str | None = None
        self._last_started_monotonic: float | None = None
        self._last_finished_at: str | None = None
        self._last_success: bool | None = None
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._last_text_length = 0
        self._last_text_preview = ""
        self._last_source: TTSSource | None = None
        self._last_job_id: int | None = None
        self._last_queued_job_id: int | None = None
        self._last_started_job_id: int | None = None
        self._last_finished_job_id: int | None = None
        self._last_dequeued_at: str | None = None
        self._last_init_started_at: str | None = None
        self._last_init_finished_at: str | None = None
        self._last_run_and_wait_started_at: str | None = None
        self._last_run_and_wait_finished_at: str | None = None
        self._last_run_and_wait_started_monotonic: float | None = None
        self._current_voice: dict[str, Any] = {"id": None, "name": None, "languages": []}
        self._job_history: list[dict[str, Any]] = []

    def enqueue(
        self,
        text: str,
        *,
        source: TTSSource,
        on_start: Callable[[], None] | None = None,
        on_finish: Callable[[bool], None] | None = None,
    ) -> dict[str, Any]:
        if self._stopped:
            return {"ok": False, "queued": False, "error": "runner_shutdown", "playbackTarget": self.config.tts_playback_target}
        if self.status()["maybeStuck"]:
            return {"ok": False, "queued": False, "error": "tts_queue_stuck", "playbackTarget": self.config.tts_playback_target}
        self._ensure_worker()
        queued_at_iso = _now_iso()
        with self._lock:
            self._next_job_id += 1
            job_id = self._next_job_id
        job = TTSJob(
            job_id=job_id,
            text=text,
            source=source,
            queued_at=time.monotonic(),
            queued_at_iso=queued_at_iso,
            preview=text[:30],
            on_start=on_start,
            on_finish=on_finish,
        )
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            return {"ok": False, "queued": False, "error": "tts_queue_full", "playbackTarget": self.config.tts_playback_target}
        with self._lock:
            self._jobs_queued += 1
            self._last_job_id = job_id
            self._last_queued_job_id = job_id
            self._last_queued_at = queued_at_iso
            self._last_source = source
            self._last_text_length = len(text)
            self._last_text_preview = job.preview
            self._upsert_job_record(
                {
                    "jobId": job_id,
                    "source": source,
                    "status": "queued",
                    "success": None,
                    "error": None,
                    "queuedAt": queued_at_iso,
                    "startedAt": None,
                    "initStartedAt": None,
                    "initFinishedAt": None,
                    "runAndWaitStartedAt": None,
                    "runAndWaitFinishedAt": None,
                    "finishedAt": None,
                    "textLength": len(text),
                    "preview": job.preview,
                }
            )
        logger.debug("voice tts queued: job_id=%s, source=%s, length=%s, queue_size=%s", job_id, source, len(text), self._queue.qsize())
        return {"ok": True, "queued": True, "job_id": job_id, "playbackTarget": self.config.tts_playback_target}

    def status(self) -> dict[str, Any]:
        from app.voice.config import resolve_effective_tts_params

        effective = resolve_effective_tts_params(self.config)
        with self._lock:
            duration_ms = 0
            if self._speaking and self._last_run_and_wait_started_monotonic is not None:
                duration_ms = int((time.monotonic() - self._last_run_and_wait_started_monotonic) * 1000)
            maybe_stuck = (
                self._speaking
                and self._last_run_and_wait_started_monotonic is not None
                and duration_ms > self.stuck_threshold_seconds * 1000
            )
            worker_alive = self._worker is not None and self._worker.is_alive()
            job_history = [_job_record_view(record) for record in self._job_history]
            last_job = None
            for record in reversed(job_history):
                last_job = record.get("status")
                break
            return {
                "queueInitialized": self._queue_initialized,
                "speaking": self._speaking,
                "queueSize": self._queue.qsize() if self._queue_initialized else 0,
                "maxQueueSize": self.max_queue_size,
                "lastQueuedAt": self._last_queued_at,
                "lastStartedAt": self._last_started_at,
                "lastFinishedAt": self._last_finished_at,
                "lastSuccess": self._last_success,
                "lastError": self._last_error,
                "lastErrorAt": self._last_error_at,
                "lastTextLength": self._last_text_length,
                "lastTextPreview": self._last_text_preview,
                "currentVoice": self._current_voice,
                "playbackTarget": self.config.tts_playback_target,
                "currentDurationMs": duration_ms,
                "maybeStuck": maybe_stuck,
                "lastSource": self._last_source,
                "workerAlive": worker_alive,
                "workerRestartCount": self._worker_restart_count,
                "jobsQueued": self._jobs_queued,
                "jobsStarted": self._jobs_started,
                "jobsFinished": self._jobs_finished,
                "totalSuccesses": self._total_successes,
                "totalFailures": self._total_failures,
                "lastJobId": self._last_job_id,
                "lastQueuedJobId": self._last_queued_job_id,
                "lastStartedJobId": self._last_started_job_id,
                "lastFinishedJobId": self._last_finished_job_id,
                "lastDequeuedAt": self._last_dequeued_at,
                "lastInitStartedAt": self._last_init_started_at,
                "lastInitFinishedAt": self._last_init_finished_at,
                "lastRunAndWaitStartedAt": self._last_run_and_wait_started_at,
                "lastRunAndWaitFinishedAt": self._last_run_and_wait_finished_at,
                "jobHistory": job_history,
                "latestManualJob": _latest_job(job_history, "manual"),
                "latestAutoJob": _latest_job(job_history, "auto"),
                "enabled": effective["enabled"],
                "requestedProvider": effective["requestedProvider"],
                "resolvedProvider": effective["resolvedProvider"],
                "providerFallbackReason": effective["providerFallbackReason"],
                "provider": effective["resolvedProvider"],
                "style": effective["style"],
                "configuredVoice": effective["configuredVoice"],
                "resolvedVoice": effective["resolvedVoice"],
                "resolvedVoiceAvailable": effective["resolvedVoiceAvailable"],
                "resolvedVoiceUnavailableReason": effective["resolvedVoiceUnavailableReason"],
                "voiceFallbackReason": effective["voiceFallbackReason"],
                "rate": effective["rate"],
                "volume": effective["volume"],
                "configuredPitch": effective["configuredPitch"],
                "appliedPitch": effective["appliedPitch"],
                "lang": effective["lang"],
                "legacyConfigUsed": effective["legacyConfigUsed"],
                "providerCapabilities": effective["providerCapabilities"],
                "unsupportedParams": effective["unsupportedParams"],
                "effectiveConfig": effective["effectiveConfig"],
                "lastJobStatus": last_job,
                "updatedAt": _now_iso(),
            }

    def shutdown(self, timeout: float = 0.5) -> None:
        self._stopped = True
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=timeout)

    def wait_until_idle(self, timeout: float = 2.0) -> bool:
        completed = threading.Event()

        def wait_for_join() -> None:
            self._queue.join()
            completed.set()

        waiter = threading.Thread(target=wait_for_join, name="voice-tts-waiter", daemon=True)
        waiter.start()
        return completed.wait(timeout=timeout)

    def stop(self) -> None:
        provider = self._provider
        if provider:
            provider.stop()

    def is_speaking(self) -> bool:
        return self.status()["speaking"]

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            if self._queue_initialized:
                self._worker_restart_count += 1
            self._stop_event.clear()
            self._worker = threading.Thread(target=self._run_worker, name="voice-tts-worker", daemon=True)
            self._queue_initialized = True
            self._worker.start()

    def _run_worker(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    job = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                success = False
                error: str | None = None
                try:
                    self._mark_job_started(job)
                    if job.on_start:
                        job.on_start()
                    logger.debug("voice tts speak started: job_id=%s, source=%s, length=%s", job.job_id, job.source, len(job.text))
                    provider = self._get_provider(job.job_id)
                    provider.speak(job.text)
                    success = True
                    logger.debug("voice tts speak finished: job_id=%s", job.job_id)
                except Exception as exc:
                    error = _summarize_error(exc)
                    logger.exception("voice tts speak error: job_id=%s, error=%s", job.job_id, error)
                finally:
                    self._finish_job(job, success, error)
                    if job.on_finish:
                        try:
                            job.on_finish(success)
                        except Exception as exc:
                            logger.exception("voice tts finish callback error: %s", _summarize_error(exc))
                    self._queue.task_done()
        except Exception as exc:
            summary = _summarize_error(exc)
            logger.exception("voice tts worker crashed: %s", summary)
            with self._lock:
                self._last_error = summary
                self._last_error_at = _now_iso()
                self._speaking = False

    def _get_provider(self, job_id: int) -> TTSProvider:
        if self._provider is None:
            self._provider = self.provider_factory()
        self._provider.set_event_callback(lambda event: self._record_provider_event(job_id, event))
        return self._provider

    def _mark_job_started(self, job: TTSJob) -> None:
        now = _now_iso()
        with self._lock:
            self._speaking = True
            self._jobs_started += 1
            self._last_job_id = job.job_id
            self._last_started_job_id = job.job_id
            self._last_started_at = now
            self._last_dequeued_at = now
            self._last_started_monotonic = time.monotonic()
            self._last_finished_at = None
            self._last_success = None
            self._last_source = job.source
            self._last_text_length = len(job.text)
            self._last_text_preview = job.preview
            self._last_init_started_at = None
            self._last_init_finished_at = None
            self._last_run_and_wait_started_at = None
            self._last_run_and_wait_finished_at = None
            self._last_run_and_wait_started_monotonic = None
            self._update_job_record(
                job.job_id,
                {
                    "status": "running",
                    "startedAt": now,
                },
            )

    def _finish_job(self, job: TTSJob, success: bool, error: str | None) -> None:
        finished_at = _now_iso()
        try:
            if self._provider:
                self._current_voice = self._provider.current_voice()
        except Exception as exc:
            logger.exception("voice tts current voice read error: %s", _summarize_error(exc))
            self._current_voice = {"id": None, "name": "default", "languages": []}
        with self._lock:
            self._speaking = False
            self._jobs_finished += 1
            self._last_finished_at = finished_at
            self._last_finished_job_id = job.job_id
            self._last_success = success
            self._last_started_monotonic = None
            self._last_run_and_wait_started_monotonic = None
            if success:
                self._total_successes += 1
            else:
                self._total_failures += 1
                self._last_error = error or "tts_error"
                self._last_error_at = finished_at
            self._update_job_record(
                job.job_id,
                {
                    "status": "success" if success else "failed",
                    "success": success,
                    "error": None if success else (error or "tts_error"),
                    "finishedAt": finished_at,
                },
            )

    def _record_provider_event(self, job_id: int, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        now = _now_iso()
        updates: dict[str, Any] = {}
        with self._lock:
            if event_type == "init_started":
                self._last_init_started_at = now
                updates["initStartedAt"] = now
            elif event_type == "init_finished":
                self._last_init_finished_at = now
                updates["initFinishedAt"] = now
            elif event_type == "run_and_wait_started":
                self._last_run_and_wait_started_at = now
                self._last_run_and_wait_started_monotonic = time.monotonic()
                updates["runAndWaitStartedAt"] = now
            elif event_type == "run_and_wait_finished":
                self._last_run_and_wait_finished_at = now
                updates["runAndWaitFinishedAt"] = now
            elif event_type == "voice_selected":
                voice = event.get("voice")
                if isinstance(voice, dict):
                    self._current_voice = voice
            if updates:
                self._update_job_record(job_id, updates)

    def _upsert_job_record(self, record: dict[str, Any]) -> None:
        existing = self._find_job_record(record["jobId"])
        if existing is None:
            self._job_history.append(record)
            if len(self._job_history) > 10:
                self._job_history = self._job_history[-10:]
        else:
            existing.update(record)

    def _update_job_record(self, job_id: int, updates: dict[str, Any]) -> None:
        record = self._find_job_record(job_id)
        if record is not None:
            record.update(updates)

    def _find_job_record(self, job_id: int) -> dict[str, Any] | None:
        return next((record for record in self._job_history if record["jobId"] == job_id), None)


def _job_record_view(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": record.get("jobId"),
        "source": record.get("source"),
        "status": record.get("status", "queued"),
        "success": record.get("success"),
        "error": record.get("error"),
        "queuedAt": record.get("queuedAt"),
        "startedAt": record.get("startedAt"),
        "initStartedAt": record.get("initStartedAt"),
        "initFinishedAt": record.get("initFinishedAt"),
        "runAndWaitStartedAt": record.get("runAndWaitStartedAt"),
        "runAndWaitFinishedAt": record.get("runAndWaitFinishedAt"),
        "finishedAt": record.get("finishedAt"),
        "textLength": record.get("textLength", len(str(record.get("preview", "")))),
        "preview": str(record.get("preview", ""))[:30],
    }


def _latest_job(job_history: list[dict[str, Any]], source: TTSSource) -> dict[str, Any] | None:
    matches = [job for job in job_history if job.get("source") == source]
    if not matches:
        return None

    def sort_key(job: dict[str, Any]) -> tuple[str, int]:
        job_id = job.get("jobId")
        return str(job.get("queuedAt") or ""), job_id if isinstance(job_id, int) else -1

    return dict(max(matches, key=sort_key))


def default_tts_status(config: VoiceConfig, max_queue_size: int = 10) -> dict[str, Any]:
    from app.voice.config import resolve_effective_tts_params

    effective = resolve_effective_tts_params(config)
    last_job_status = None
    return {
        "queueInitialized": False,
        "speaking": False,
        "queueSize": 0,
        "maxQueueSize": max_queue_size,
        "lastQueuedAt": None,
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastSuccess": None,
        "lastError": None,
        "lastErrorAt": None,
        "lastTextLength": 0,
        "lastTextPreview": "",
        "currentVoice": {"id": None, "name": None, "languages": []},
        "playbackTarget": config.tts_playback_target,
        "currentDurationMs": 0,
        "maybeStuck": False,
        "lastSource": None,
        "workerAlive": False,
        "workerRestartCount": 0,
        "jobsQueued": 0,
        "jobsStarted": 0,
        "jobsFinished": 0,
        "totalSuccesses": 0,
        "totalFailures": 0,
        "lastJobId": None,
        "lastQueuedJobId": None,
        "lastStartedJobId": None,
        "lastFinishedJobId": None,
        "lastDequeuedAt": None,
        "lastInitStartedAt": None,
        "lastInitFinishedAt": None,
        "lastRunAndWaitStartedAt": None,
        "lastRunAndWaitFinishedAt": None,
        "jobHistory": [],
        "latestManualJob": None,
        "latestAutoJob": None,
        "enabled": effective["enabled"],
        "requestedProvider": effective["requestedProvider"],
        "resolvedProvider": effective["resolvedProvider"],
        "providerFallbackReason": effective["providerFallbackReason"],
        "provider": effective["resolvedProvider"],
        "style": effective["style"],
        "configuredVoice": effective["configuredVoice"],
        "resolvedVoice": effective["resolvedVoice"],
        "resolvedVoiceAvailable": effective["resolvedVoiceAvailable"],
        "resolvedVoiceUnavailableReason": effective["resolvedVoiceUnavailableReason"],
        "voiceFallbackReason": effective["voiceFallbackReason"],
        "rate": effective["rate"],
        "volume": effective["volume"],
        "configuredPitch": effective["configuredPitch"],
        "appliedPitch": effective["appliedPitch"],
        "lang": effective["lang"],
        "legacyConfigUsed": effective["legacyConfigUsed"],
        "providerCapabilities": effective["providerCapabilities"],
        "unsupportedParams": effective["unsupportedParams"],
        "effectiveConfig": effective["effectiveConfig"],
        "lastJobStatus": last_job_status,
        "lastTextPreview": None,
        "updatedAt": _now_iso(),
    }
