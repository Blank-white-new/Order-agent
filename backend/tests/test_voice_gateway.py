import asyncio
import logging
import threading
import time

from app.agents.voice_gateway_agent import VoiceGatewayAgent
from app.agents.orchestrator import OrchestratorAgent
from app.services.text_entry_service import TextEntryService
from app.state.session_store import InMemorySessionStore
from app.voice.asr.base import ASRProvider
from app.voice.config import VoiceConfig
from app.voice.runtime import create_voice_runtime
from app.voice.session import VoiceSessionController
from app.voice.text_cleaner import clean_text_for_tts, is_empty_transcript, normalize_voice_transcript
from app.voice.tts.base import TTSProvider
from app.voice.tts.pyttsx3_tts import Pyttsx3TTSProvider
from app.voice.tts.runner import AsyncTTSRunner


class FakeTextEntryService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def handle_text_message(self, session_id: str, text: str) -> dict:
        self.calls.append((session_id, text))
        return {
            "session_id": session_id,
            "response": f"店员回复:{text}",
            "state": {"current_order": []},
            "trace": {"finalIntent": "mock"},
        }


class FixedReplyTextEntry(FakeTextEntryService):
    def __init__(self, response: str) -> None:
        super().__init__()
        self.response = response

    async def handle_text_message(self, session_id: str, text: str) -> dict:
        self.calls.append((session_id, text))
        return {
            "session_id": session_id,
            "response": self.response,
            "state": {"current_order": []},
            "trace": {"finalIntent": "mock"},
        }


class LockTrackingTextEntry(FakeTextEntryService):
    def __init__(self) -> None:
        super().__init__()
        self.in_handle = False

    async def handle_text_message(self, session_id: str, text: str) -> dict:
        self.in_handle = True
        await asyncio.sleep(0.01)
        result = await super().handle_text_message(session_id, text)
        self.in_handle = False
        return result


class PartialASR(ASRProvider):
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def accept_audio_chunk(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    def get_partial_transcript(self) -> str:
        return "来一份"

    def get_final_transcript(self) -> str:
        return "来一份黑椒牛肉饭"

    def reset(self) -> None:
        self.chunks = []


class SlowTTS(TTSProvider):
    def __init__(self, delay: float = 0.2) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self.speaking = False

    def speak(self, text: str) -> None:
        self.speaking = True
        self.calls.append(text)
        time.sleep(self.delay)
        self.speaking = False

    def stop(self) -> None:
        self.speaking = False

    def is_speaking(self) -> bool:
        return self.speaking


class FailingTTS(SlowTTS):
    def speak(self, text: str) -> None:
        self.calls.append(text)
        raise RuntimeError("tts failed")


class AssertOutsideTextEntryTTS(SlowTTS):
    def __init__(self, text_entry: LockTrackingTextEntry) -> None:
        super().__init__(delay=0)
        self.text_entry = text_entry

    def speak(self, text: str) -> None:
        assert self.text_entry.in_handle is False
        super().speak(text)


class BlockingTTS(TTSProvider):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def speak(self, text: str) -> None:
        self.calls.append(text)
        self.started.set()
        self.release.wait(timeout=2)

    def stop(self) -> None:
        self.release.set()

    def is_speaking(self) -> bool:
        return self.started.is_set() and not self.release.is_set()


class NonInterruptibleBlockingTTS(TTSProvider):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []
        self.stop_calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def speak(self, text: str) -> None:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(text)
        self.started.set()
        self.release.wait(timeout=2)
        with self.lock:
            self.active -= 1

    def stop(self) -> None:
        self.stop_calls += 1

    def is_speaking(self) -> bool:
        return self.started.is_set() and not self.release.is_set()


class SequenceTTS(TTSProvider):
    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls: list[str] = []

    def speak(self, text: str) -> None:
        self.calls.append(text)
        if len(self.calls) in self.fail_on:
            raise RuntimeError(f"tts failure #{len(self.calls)}")

    def stop(self) -> None:
        pass

    def is_speaking(self) -> bool:
        return False

    def current_voice(self) -> dict:
        return {"id": "sequence-id", "name": "Sequence Voice", "languages": ["zh"]}


def make_gateway(text_entry: FakeTextEntryService | None = None, tts: TTSProvider | None = None) -> VoiceGatewayAgent:
    return VoiceGatewayAgent(
        text_entry_service=text_entry or FakeTextEntryService(),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=tts is not None),
        tts_provider=tts,
    )


def enable_tts_for(gateway: VoiceGatewayAgent, session_id: str, utterance_id: str) -> None:
    gateway.begin_utterance(session_id, utterance_id, tts_enabled=True)


def test_partial_transcript_does_not_call_text_entry():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry)

    event = gateway.on_partial_transcript("s1", "我想点")

    assert event == {"type": "partial", "text": "我想点"}
    assert text_entry.calls == []


def test_final_transcript_calls_text_entry_once_and_preserves_text():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry)

    events = asyncio.run(gateway.on_final_transcript("s1", "u1", "来一份黑椒牛肉饭"))

    assert text_entry.calls == [("s1", "来一份黑椒牛肉饭")]
    assert [event["type"] for event in events][:2] == ["final", "agent_reply"]
    assert events[0]["text"] == "来一份黑椒牛肉饭"


def test_spaced_asr_final_transcript_calls_text_entry_with_normalized_text():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry)

    events = asyncio.run(gateway.on_final_transcript("s1", "u-spaced", "来 一 份 黑 椒 牛 肉 饭"))

    assert text_entry.calls == [("s1", "来一份黑椒牛肉饭")]
    assert events[0]["text"] == "来一份黑椒牛肉饭"


def test_empty_or_filler_final_is_ignored():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry)

    events = asyncio.run(gateway.on_final_transcript("s1", "u-empty", " 嗯 啊 那个 就是 "))

    assert events == [
        {"type": "ignored_empty_transcript", "utterance_id": "u-empty", "ignored": True},
        {
            "type": "tts_status",
            "utterance_id": "u-empty",
            "source": "auto",
            "queued": False,
            "reason": "ignored_empty_transcript",
            "job_id": None,
            "tts_enabled": False,
        },
    ]
    assert text_entry.calls == []


def test_voice_normalization_compacts_cjk_asr_spacing_without_changing_menu_words():
    assert normalize_voice_transcript("来 一 份 黑 椒 牛 肉 饭") == "来一份黑椒牛肉饭"
    assert normalize_voice_transcript("鸡 腿 饭 不 辣") == "鸡腿饭不辣"
    assert normalize_voice_transcript("hello world") == "hello world"


def test_spaced_filler_only_transcript_is_ignored():
    assert is_empty_transcript("嗯 啊 那个 就是") is True


def test_duplicate_utterance_does_not_call_text_entry_or_tts_again():
    text_entry = FakeTextEntryService()
    tts = SlowTTS(delay=0.01)
    gateway = make_gateway(text_entry, tts)
    enable_tts_for(gateway, "s1", "same-u")

    first = asyncio.run(gateway.on_final_transcript("s1", "same-u", "来一份黑椒牛肉饭"))
    second = asyncio.run(gateway.on_final_transcript("s1", "same-u", "来一份黑椒牛肉饭"))
    asyncio.run(gateway.wait_for_tts_tasks())

    assert [event["type"] for event in first] == ["final", "agent_reply", "tts_status"]
    assert first[-1]["queued"] is True
    assert first[-1]["job_id"] == 1
    assert first[-1]["source"] == "auto"
    assert second == [
        {"type": "duplicate_utterance", "utterance_id": "same-u", "ignored": True},
        {
            "type": "tts_status",
            "utterance_id": "same-u",
            "source": "auto",
            "queued": False,
            "reason": "duplicate_utterance",
            "job_id": None,
            "tts_enabled": True,
        },
    ]
    assert text_entry.calls == [("s1", "来一份黑椒牛肉饭")]
    assert len(tts.calls) == 1


def test_tts_runs_in_background_and_mutes_session():
    text_entry = FakeTextEntryService()
    tts = SlowTTS(delay=0.2)
    gateway = make_gateway(text_entry, tts)

    async def run() -> tuple[list[dict], float, dict]:
        enable_tts_for(gateway, "s1", "u1")
        start = time.perf_counter()
        events = await gateway.on_final_transcript("s1", "u1", "来一份黑椒牛肉饭")
        duration = time.perf_counter() - start
        await gateway.wait_for_tts_tasks()
        return events, duration, gateway.tts_status()

    events, duration, status = asyncio.run(run())

    assert duration < 0.1
    assert events[-1]["type"] == "tts_status"
    assert events[-1]["queued"] is True
    assert status["lastSuccess"] is True
    assert status["lastError"] is None
    assert gateway.session_controller.get_session("s1").muted is False


def test_tts_failure_does_not_affect_text_order_result():
    text_entry = FakeTextEntryService()
    tts = FailingTTS(delay=0)
    gateway = make_gateway(text_entry, tts)

    async def run() -> list[dict]:
        enable_tts_for(gateway, "s1", "u1")
        events = await gateway.on_final_transcript("s1", "u1", "来一份黑椒牛肉饭")
        await gateway.wait_for_tts_tasks()
        return events

    events = asyncio.run(run())

    assert [event["type"] for event in events] == ["final", "agent_reply", "tts_status"]
    assert events[-1]["queued"] is True
    assert gateway.tts_status()["lastSuccess"] is False
    assert "RuntimeError" in gateway.tts_status()["lastError"]
    assert text_entry.calls == [("s1", "来一份黑椒牛肉饭")]
    assert tts.calls == ["店员回复:来一份黑椒牛肉饭"]


def test_tts_is_not_executed_while_text_entry_is_in_progress():
    text_entry = LockTrackingTextEntry()
    tts = AssertOutsideTextEntryTTS(text_entry)
    gateway = make_gateway(text_entry, tts)

    async def run() -> None:
        enable_tts_for(gateway, "s1", "u1")
        await gateway.on_final_transcript("s1", "u1", "来一份黑椒牛肉饭")
        await gateway.wait_for_tts_tasks()

    asyncio.run(run())

    assert tts.calls == ["店员回复:来一份黑椒牛肉饭"]


def test_auto_tts_debug_logs_success_when_enabled(caplog):
    caplog.set_level(logging.INFO)
    text_entry = FixedReplyTextEntry("auto debug reply that should be truncated before logging")
    tts = SequenceTTS()
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=tts,
    )

    enable_tts_for(gateway, "debug-success", "u-debug")
    events = asyncio.run(gateway.on_final_transcript("debug-success", "u-debug", "order rice"))
    asyncio.run(gateway.wait_for_tts_tasks())

    assert events[-1]["queued"] is True
    log_text = caplog.text
    for token in [
        "[voice-auto-tts]",
        "start_utterance.tts_enabled",
        "preference_saved",
        "final_text_length",
        "agent_reply_length",
        "preference_lookup_found",
        "cleaned_tts_text_length",
        "queue_tts_called",
        "queue_tts_result",
        "runtimeId",
        "runnerId",
        "job_id",
    ]:
        assert token in log_text
    assert "auto debug reply that should be truncated before logging" not in log_text


def test_auto_tts_debug_is_quiet_by_default(caplog):
    caplog.set_level(logging.INFO)
    text_entry = FixedReplyTextEntry("auto debug reply")
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=False),
        tts_provider=SequenceTTS(),
    )

    enable_tts_for(gateway, "debug-off", "u-debug-off")
    asyncio.run(gateway.on_final_transcript("debug-off", "u-debug-off", "order rice"))
    asyncio.run(gateway.wait_for_tts_tasks())

    assert "[voice-auto-tts]" not in caplog.text


def test_auto_tts_debug_logs_skip_reasons(caplog, monkeypatch):
    caplog.set_level(logging.INFO)

    preference_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry("auto debug reply"),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    asyncio.run(preference_gateway.on_final_transcript("debug-pref", "u-pref", "order rice"))
    assert "preference_missing" in caplog.text
    assert "tts_enabled=false" in caplog.text

    caplog.clear()
    duplicate_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry("auto debug reply"),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    enable_tts_for(duplicate_gateway, "debug-dup", "u-dup")
    asyncio.run(duplicate_gateway.on_final_transcript("debug-dup", "u-dup", "order rice"))
    asyncio.run(duplicate_gateway.on_final_transcript("debug-dup", "u-dup", "order rice"))
    assert "duplicate_utterance" in caplog.text

    caplog.clear()
    empty_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry("auto debug reply"),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    asyncio.run(empty_gateway.on_final_transcript("debug-empty", "u-empty", " "))
    assert "ignored_empty_transcript" in caplog.text

    caplog.clear()
    agent_empty_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry(""),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    enable_tts_for(agent_empty_gateway, "debug-agent-empty", "u-agent-empty")
    asyncio.run(agent_empty_gateway.on_final_transcript("debug-agent-empty", "u-agent-empty", "order rice"))
    assert "agent_reply_empty" in caplog.text

    caplog.clear()
    cleaned_empty_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry('```json\n{"trace":1}\n```'),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    enable_tts_for(cleaned_empty_gateway, "debug-cleaned-empty", "u-cleaned-empty")
    asyncio.run(cleaned_empty_gateway.on_final_transcript("debug-cleaned-empty", "u-cleaned-empty", "order rice"))
    assert "cleaned_tts_text_empty" in caplog.text

    caplog.clear()
    disabled_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry("auto debug reply"),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    enable_tts_for(disabled_gateway, "debug-disabled", "u-disabled")
    asyncio.run(disabled_gateway.on_final_transcript("debug-disabled", "u-disabled", "order rice"))
    assert "tts_disabled" in caplog.text

    caplog.clear()
    import app.voice.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "evaluate_voice_status", lambda *_args, **_kwargs: {"ttsReady": False})
    unavailable_gateway = VoiceGatewayAgent(
        text_entry_service=FixedReplyTextEntry("auto debug reply"),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True, voice_debug=True),
        tts_provider=SequenceTTS(),
    )
    enable_tts_for(unavailable_gateway, "debug-unavailable", "u-unavailable")
    asyncio.run(unavailable_gateway.on_final_transcript("debug-unavailable", "u-unavailable", "order rice"))
    assert "can_speak_false" in caplog.text


def test_audio_chunk_is_accepted_while_muted_or_speaking():
    gateway = make_gateway()
    session = gateway.session_controller.get_session("s1")
    recognizer = PartialASR()
    session.recognizer = recognizer
    session.muted = True
    session.status = "speaking"

    events = asyncio.run(gateway.on_audio_chunk("s1", b"pcm"))

    assert events == [{"type": "partial", "text": "来一份"}]
    assert recognizer.chunks == [b"pcm"]


def test_final_transcript_stops_tts_before_text_entry():
    text_entry = FakeTextEntryService()
    tts = BlockingTTS()
    gateway = make_gateway(text_entry, tts)
    queued = gateway.runtime.queue_tts("旧播报", source="manual")
    assert queued["queued"] is True
    assert tts.started.wait(timeout=1)

    events = asyncio.run(gateway.on_final_transcript("s1", "u1", "来一份黑椒牛肉饭"))
    asyncio.run(gateway.wait_for_tts_tasks())
    status = gateway.tts_status()

    assert [event["type"] for event in events][:2] == ["final", "agent_reply"]
    assert text_entry.calls == [("s1", "来一份黑椒牛肉饭")]
    assert status["lastInterruptedAt"] is not None


def test_same_transcript_in_different_utterances_is_not_deduped():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry)

    asyncio.run(gateway.on_final_transcript("s1", "u1", "再来一份"))
    asyncio.run(gateway.on_final_transcript("s1", "u2", "再来一份"))

    assert text_entry.calls == [("s1", "再来一份"), ("s1", "再来一份")]


def test_recent_tts_echo_without_active_utterance_is_ignored():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry, SequenceTTS())

    gateway.runtime.queue_tts("已加入一份黑椒牛肉饭", source="manual")
    asyncio.run(gateway.wait_for_tts_tasks())

    events = asyncio.run(gateway.on_final_transcript("s1", "echo-u", "已加入一份黑椒牛肉饭"))

    assert events[0] == {"type": "ignored_empty_transcript", "utterance_id": "echo-u", "ignored": True}
    assert text_entry.calls == []


def test_active_user_round_can_repeat_recent_tts_text():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry, SequenceTTS())

    gateway.runtime.queue_tts("确认", source="manual")
    asyncio.run(gateway.wait_for_tts_tasks())
    gateway.begin_utterance("s1", "u-confirm", tts_enabled=False)

    events = asyncio.run(gateway.on_final_transcript("s1", "u-confirm", "确认"))

    assert [event["type"] for event in events][:2] == ["final", "agent_reply"]
    assert text_entry.calls == [("s1", "确认")]


def test_active_user_round_can_repeat_recent_tts_menu_item():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry, SequenceTTS())

    gateway.runtime.queue_tts("黑椒牛肉饭", source="manual")
    asyncio.run(gateway.wait_for_tts_tasks())
    gateway.begin_utterance("s1", "u-menu-item", tts_enabled=False)

    events = asyncio.run(gateway.on_final_transcript("s1", "u-menu-item", "黑椒牛肉饭"))

    assert [event["type"] for event in events][:2] == ["final", "agent_reply"]
    assert text_entry.calls == [("s1", "黑椒牛肉饭")]


def test_tts_runner_reports_maybe_stuck_and_queue_full():
    blocking = BlockingTTS()
    runner = AsyncTTSRunner(lambda: blocking, VoiceConfig(voice_enabled=True, tts_enabled=True), max_queue_size=1, stuck_threshold_seconds=30)

    first = runner.enqueue("第一条", source="manual")
    assert first["queued"] is True
    assert blocking.started.wait(timeout=1)
    with runner._lock:
        runner._last_run_and_wait_started_monotonic = time.monotonic() - 31
        runner._last_run_and_wait_started_at = "started"
        runner._last_run_and_wait_finished_at = None
    status = runner.status()
    assert status["speaking"] is True
    assert status["maybeStuck"] is True
    assert status["currentDurationMs"] >= 30000
    assert runner.enqueue("第二条", source="manual")["error"] == "tts_queue_stuck"
    blocking.release.set()
    assert runner.wait_until_idle(timeout=2)
    runner.shutdown()


def test_tts_runner_processes_three_jobs_and_records_history():
    tts = SequenceTTS()
    runner = AsyncTTSRunner(lambda: tts, VoiceConfig(voice_enabled=True, tts_enabled=True))
    before = runner.status()["jobsFinished"]

    results = [runner.enqueue(f"第{index}条", source="manual") for index in range(1, 4)]
    assert [result["job_id"] for result in results] == [1, 2, 3]
    assert _wait_for_jobs(runner, before + 3)
    status = runner.status()

    assert status["jobsQueued"] >= 3
    assert status["jobsStarted"] >= 3
    assert status["jobsFinished"] >= 3
    assert status["totalSuccesses"] >= 3
    assert status["workerAlive"] is True
    assert status["speaking"] is False
    assert status["queueSize"] == 0
    assert status["maybeStuck"] is False
    history = {job["jobId"]: job for job in status["jobHistory"]}
    for job_id in [1, 2, 3]:
        assert history[job_id]["status"] == "success"
        assert history[job_id]["success"] is True
        assert {"jobId", "source", "status", "success", "error", "queuedAt", "finishedAt", "preview"} <= set(history[job_id])
        assert history[job_id]["queuedAt"]
        assert history[job_id]["startedAt"]
        assert history[job_id]["finishedAt"]
        assert history[job_id]["textLength"] > 0
    assert status["latestManualJob"]["jobId"] == 3
    assert status["latestAutoJob"] is None
    runner.shutdown()


def test_tts_runner_continues_after_middle_job_failure():
    tts = SequenceTTS(fail_on={2})
    runner = AsyncTTSRunner(lambda: tts, VoiceConfig(voice_enabled=True, tts_enabled=True))

    results = [runner.enqueue(f"第{index}条", source="manual") for index in range(1, 4)]
    assert [result["job_id"] for result in results] == [1, 2, 3]
    assert _wait_for_jobs(runner, 3)
    status = runner.status()
    history = {job["jobId"]: job for job in status["jobHistory"]}

    assert status["jobsFinished"] == 3
    assert status["totalFailures"] == 1
    assert status["lastErrorAt"] is not None
    assert status["lastError"] is not None
    assert status["lastSuccess"] is True
    assert status["workerAlive"] is True
    assert history[1]["status"] == "success"
    assert history[2]["status"] == "failed"
    assert "RuntimeError" in history[2]["error"]
    assert history[3]["status"] == "success"
    runner.shutdown()


def test_tts_runner_shutdown_is_terminal_for_instance():
    runner = AsyncTTSRunner(lambda: SequenceTTS(), VoiceConfig(voice_enabled=True, tts_enabled=True))

    runner.shutdown()
    runner.shutdown()

    result = runner.enqueue("不会播报", source="manual")
    assert result["queued"] is False
    assert result["error"] == "runner_shutdown"


def test_tts_runner_stop_clears_queue_and_old_generation_cannot_overwrite_new_status():
    blocking = BlockingTTS()
    runner = AsyncTTSRunner(lambda: blocking, VoiceConfig(voice_enabled=True, tts_enabled=True), max_queue_size=3)

    first = runner.enqueue("旧播报", source="manual")
    second = runner.enqueue("待清空播报", source="manual")
    assert first["queued"] is True
    assert second["queued"] is True
    assert blocking.started.wait(timeout=1)

    stopped = runner.stop()
    stopped_again = runner.stop()
    status_after_stop = runner.status()

    assert stopped["ok"] is True
    assert stopped["interrupted"] is True
    assert stopped["clearedJobs"] == 1
    assert stopped_again["ok"] is True
    assert status_after_stop["speaking"] is False
    assert status_after_stop["queueSize"] == 0

    next_job = runner.enqueue("新播报", source="manual")
    assert next_job["queued"] is True
    assert runner.wait_until_idle(timeout=2)
    status = runner.status()
    history = {job["jobId"]: job for job in status["jobHistory"]}

    assert history[first["job_id"]]["status"] == "interrupted"
    assert history[second["job_id"]]["status"] == "interrupted"
    assert history[next_job["job_id"]]["status"] == "success"
    assert status["lastFinishedJobId"] == next_job["job_id"]
    assert status["lastSuccess"] is True
    assert status["queueSize"] == 0
    runner.shutdown()


def test_tts_runner_stop_does_not_start_new_speech_while_provider_is_blocked():
    blocking = NonInterruptibleBlockingTTS()
    runner = AsyncTTSRunner(lambda: blocking, VoiceConfig(voice_enabled=True, tts_enabled=True), max_queue_size=3)

    first = runner.enqueue("old tts", source="manual")
    assert first["queued"] is True
    assert blocking.started.wait(timeout=1)

    stopped = runner.stop()
    stopped_again = runner.stop()
    next_job = runner.enqueue("new tts", source="manual")

    time.sleep(0.05)
    assert stopped["ok"] is True
    assert stopped["interrupted"] is True
    assert stopped_again["ok"] is True
    assert blocking.stop_calls == 2
    assert next_job["queued"] is True
    assert blocking.calls == ["old tts"]
    assert blocking.max_active == 1

    blocking.release.set()
    assert runner.wait_until_idle(timeout=2)
    status = runner.status()
    history = {job["jobId"]: job for job in status["jobHistory"]}

    assert blocking.calls == ["old tts", "new tts"]
    assert blocking.max_active == 1
    assert history[first["job_id"]]["status"] == "interrupted"
    assert history[next_job["job_id"]]["status"] == "success"
    assert status["queueSize"] == 0
    runner.shutdown()


def test_pyttsx3_provider_does_not_start_second_engine_while_old_run_is_blocked(monkeypatch):
    release = threading.Event()
    run_started = threading.Event()
    created_engines: list[FakePyttsx3Engine] = []

    class FakePyttsx3Engine:
        active_runs = 0
        max_active_runs = 0
        lock = threading.Lock()

        def __init__(self) -> None:
            self.say_calls: list[str] = []
            self.stop_calls = 0

        def setProperty(self, _name: str, _value: object) -> None:
            return None

        def getProperty(self, name: str) -> object:
            if name == "voices":
                return []
            if name == "voice":
                return None
            return None

        def say(self, text: str) -> None:
            self.say_calls.append(text)

        def runAndWait(self) -> None:
            with type(self).lock:
                type(self).active_runs += 1
                type(self).max_active_runs = max(type(self).max_active_runs, type(self).active_runs)
            run_started.set()
            release.wait(timeout=2)
            with type(self).lock:
                type(self).active_runs -= 1

        def stop(self) -> None:
            self.stop_calls += 1

    def fake_create_engine(self: Pyttsx3TTSProvider) -> FakePyttsx3Engine:
        engine = FakePyttsx3Engine()
        created_engines.append(engine)
        return engine

    monkeypatch.setattr(Pyttsx3TTSProvider, "_create_engine", fake_create_engine)
    provider = Pyttsx3TTSProvider(VoiceConfig(voice_enabled=True, tts_enabled=True))
    runner = AsyncTTSRunner(lambda: provider, provider.config, max_queue_size=3)

    first = runner.enqueue("old tts", source="manual")
    assert first["queued"] is True
    assert run_started.wait(timeout=1)

    runner.stop()
    next_job = runner.enqueue("new tts", source="manual")
    time.sleep(0.05)

    assert next_job["queued"] is True
    assert len(created_engines) == 1
    assert created_engines[0].say_calls == ["old tts"]
    assert FakePyttsx3Engine.max_active_runs == 1

    release.set()
    assert runner.wait_until_idle(timeout=2)

    assert len(created_engines) == 2
    assert created_engines[1].say_calls == ["new tts"]
    assert FakePyttsx3Engine.max_active_runs == 1
    runner.shutdown()


def test_runtime_queue_tts_ignores_asr_readiness_and_uses_unified_result():
    tts = SequenceTTS()
    runtime = create_voice_runtime(
        VoiceConfig(voice_enabled=True, tts_enabled=True, vosk_model_path="./missing-vosk-model"),
        tts_provider_factory=lambda: tts,
    )

    result = runtime.queue_tts("可以播报", source="manual")
    runtime.get_tts_runner().wait_until_idle()
    status = runtime.tts_status()

    assert result["ok"] is True
    assert result["queued"] is True
    assert result["source"] == "manual"
    assert result["reason"] is None
    assert result["job_id"] == 1
    assert status["jobHistory"][0]["source"] == "manual"
    assert status["jobHistory"][0]["status"] == "success"
    runtime.shutdown()


def test_runtime_queue_tts_preserves_runner_shutdown_reason():
    runtime = create_voice_runtime(
        VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider_factory=lambda: SequenceTTS(),
    )

    runtime.get_tts_runner().shutdown()
    result = runtime.queue_tts("不会播报", source="auto")

    assert result == {
        "ok": False,
        "queued": False,
        "job_id": None,
        "source": "auto",
        "reason": "runner_shutdown",
        "playbackTarget": "server",
    }


def test_runtime_queue_tts_returns_can_speak_false_when_tts_unavailable(monkeypatch):
    import app.voice.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "evaluate_voice_status", lambda *_args, **_kwargs: {"ttsReady": False})
    runtime = create_voice_runtime(
        VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider_factory=lambda: SequenceTTS(),
    )

    result = runtime.queue_tts("不会播报", source="auto")

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["reason"] == "can_speak_false"
    assert runtime.tts_status()["queueInitialized"] is False


def test_clean_text_for_tts_removes_debug_markup_json_and_emoji():
    cleaned = clean_text_for_tts('**好的** {"trace": {"finalIntent": "x"}} 😊\\n```json\\n{"a":1}\\n```')

    assert "trace" not in cleaned
    assert "{" not in cleaned
    assert "*" not in cleaned
    assert "😊" not in cleaned
    assert "好的" in cleaned


def test_duplicate_final_does_not_duplicate_real_order():
    store = InMemorySessionStore()
    text_entry = TextEntryService(store=store, orchestrator=OrchestratorAgent())
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False),
    )

    async def run() -> list[dict]:
        await gateway.on_final_transcript("real-order", "u1", "来一份黑椒牛肉饭")
        return await gateway.on_final_transcript("real-order", "u1", "来一份黑椒牛肉饭")

    duplicate = asyncio.run(run())
    state = store.get("real-order")

    assert duplicate == [
        {"type": "duplicate_utterance", "utterance_id": "u1", "ignored": True},
        {"type": "tts_status", "utterance_id": "u1", "source": "auto", "queued": False, "reason": "duplicate_utterance", "job_id": None, "tts_enabled": False},
    ]
    assert len(state.current_order) == 1
    assert state.current_order[0].name == "黑椒牛肉饭"


def test_voice_final_and_text_chat_share_serial_state_updates():
    store = InMemorySessionStore()
    text_entry = TextEntryService(store=store, orchestrator=OrchestratorAgent())
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False),
    )

    async def run() -> None:
        await asyncio.gather(
            gateway.on_final_transcript("mixed", "voice-1", "鸡腿饭不辣"),
            text_entry.handle_text_message("mixed", "可乐两瓶"),
        )

    asyncio.run(run())
    state = store.get("mixed")
    order = {item.name: item for item in state.current_order}

    assert set(order) == {"鸡腿饭", "可乐"}
    assert order["可乐"].quantity == 2


def test_mock_voice_regression_scenarios_call_text_entry_once_each():
    text_entry = FakeTextEntryService()
    gateway = make_gateway(text_entry)
    messages = [
        "你好，想点餐",
        "招牌菜是啥",
        "来一份黑椒牛肉饭",
        "不要牛肉饭",
        "配送",
        "中山大学深圳校区",
        "改成自取",
        "刚刚说错了",
        "有没有不辣的",
        "确认下单",
    ]

    async def run() -> None:
        for index, message in enumerate(messages):
            await gateway.on_final_transcript("mock-e2e", f"u-{index}", message)

    asyncio.run(run())

    expected = ["你好,想点餐", *messages[1:]]
    assert [call[1] for call in text_entry.calls] == expected


def _wait_for_jobs(runner: AsyncTTSRunner, finished_target: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = runner.status()
        if status["jobsFinished"] >= finished_target and status["queueSize"] == 0 and status["speaking"] is False:
            return True
        time.sleep(0.05)
    return False
