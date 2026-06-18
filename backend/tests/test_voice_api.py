import time

import threading

from fastapi.testclient import TestClient

from app.agents.voice_gateway_agent import VoiceGatewayAgent
from app.main import app
from app.services.text_entry_service import TextEntryService
from app.state.session_store import InMemorySessionStore
from app.state.session_state import SessionState
from app.voice.asr.base import ASRProvider
from app.voice.config import VoiceConfig, clear_settings_cache
from app.voice.runtime import create_voice_runtime
from app.voice.session import VoiceSessionController
from app.voice.tts.base import TTSProvider


class FixedFinalASR(ASRProvider):
    released = False

    def start(self) -> None:
        type(self).released = False

    def stop(self) -> None:
        type(self).released = True

    def accept_audio_chunk(self, chunk: bytes) -> None:
        pass

    def get_partial_transcript(self) -> str:
        return ""

    def get_final_transcript(self) -> str:
        return "来一份黑椒牛肉饭"

    def reset(self) -> None:
        pass


class ChunkFinalASR(ASRProvider):
    chunks: list[bytes] = []

    def start(self) -> None:
        type(self).chunks = []

    def stop(self) -> None:
        pass

    def accept_audio_chunk(self, chunk: bytes) -> None:
        type(self).chunks.append(chunk)

    def get_partial_transcript(self) -> str:
        return "来一份"

    def get_final_transcript(self) -> str:
        return "来一份黑椒牛肉饭"

    def reset(self) -> None:
        pass


class CountingOrchestrator:
    def __init__(self) -> None:
        self.calls = 0

    def handle_user_message(self, message: str, state: SessionState) -> dict:
        self.calls += 1
        return {
            "response": f"已处理:{message}",
            "state": state.serializable(),
            "trace": {"finalIntent": "mock"},
            "raw_state": state,
        }


class RecordingTTS(TTSProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.speaking = False

    def speak(self, text: str) -> None:
        self.speaking = True
        self.calls.append(text)
        self.speaking = False

    def stop(self) -> None:
        self.speaking = False

    def is_speaking(self) -> bool:
        return self.speaking

    def current_voice(self) -> dict:
        return {"id": "fake-id", "name": "Fake Voice", "languages": ["zh"]}


class FailingTTS(RecordingTTS):
    def speak(self, text: str) -> None:
        self.calls.append(text)
        raise RuntimeError("tts failed")


class BlockingTTS(TTSProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.speaking = False

    def speak(self, text: str) -> None:
        self.calls.append(text)
        self.speaking = True
        self.started.set()
        self.release.wait(timeout=2)
        self.speaking = False

    def stop(self) -> None:
        self.speaking = False
        self.release.set()

    def is_speaking(self) -> bool:
        return self.speaking


def test_voice_status_disabled_is_safe(monkeypatch):
    import app.api.voice as voice_api

    monkeypatch.setenv("VOICE_ENABLED", "false")
    clear_settings_cache()
    runtime = create_voice_runtime(VoiceConfig(voice_enabled=False, tts_enabled=True))
    voice_api.reset_voice_runtime_for_test(runtime)
    client = TestClient(app)

    response = client.get("/api/voice/status")

    assert response.status_code == 200
    body = response.json()
    assert body["voiceEnabled"] is False
    assert "asrEngine" in body
    assert body["canRecord"] is False


def test_tts_status_before_runner_initialization(monkeypatch):
    import app.api.voice as voice_api

    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider=RecordingTTS(),
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)

    response = TestClient(app).get("/api/voice/tts/status")

    assert response.status_code == 200
    body = response.json()
    assert body["queueInitialized"] is False
    assert body["speaking"] is False
    assert body["queueSize"] == 0
    assert body["lastSuccess"] is None
    assert body["currentVoice"] == {"id": None, "name": None, "languages": []}
    assert body["lastSource"] is None
    assert body["jobHistory"] == []
    assert body["latestManualJob"] is None
    assert body["latestAutoJob"] is None
    assert gateway.runtime._tts_runner is None


def test_voice_tts_empty_text_is_ignored(monkeypatch):
    import app.api.voice as voice_api

    tts = RecordingTTS()
    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)

    response = TestClient(app).post("/api/voice/tts", json={"text": "```json\n{\"trace\": 1}\n```"})

    assert response.status_code == 200
    assert response.json()["error"] == "ignored_empty_tts_text"
    assert tts.calls == []


def test_voice_tts_queues_manual_source_and_status_records_success(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    tts = RecordingTTS()
    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    client = TestClient(app)

    response = client.post("/api/voice/tts", json={"text": "这是一条语音播报测试。"})
    asyncio.run(gateway.wait_for_tts_tasks())
    status = client.get("/api/voice/tts/status").json()

    assert response.json()["queued"] is True
    assert response.json()["job_id"] == 1
    assert tts.calls == ["这是一条语音播报测试。"]
    assert status["queueInitialized"] is True
    assert status["lastSource"] == "manual"
    assert status["lastSuccess"] is True
    assert status["lastError"] is None
    assert status["currentVoice"]["name"] == "Fake Voice"


def test_voice_tts_three_manual_posts_finish_and_enter_history(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    tts = RecordingTTS()
    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    client = TestClient(app)
    before = client.get("/api/voice/tts/status").json()["jobsFinished"]

    responses = [
        client.post("/api/voice/tts", json={"text": f"测试播报 {index}"}).json()
        for index in range(1, 4)
    ]
    job_ids = [response["job_id"] for response in responses]
    assert len(set(job_ids)) == 3

    asyncio.run(gateway.wait_for_tts_tasks())
    status = _poll_tts_status(client, before + 3)
    history = {job["jobId"]: job for job in status["jobHistory"]}

    assert status["jobsFinished"] >= before + 3
    assert status["jobsStarted"] >= before + 3
    assert status["queueSize"] == 0
    assert status["speaking"] is False
    assert status["maybeStuck"] is False
    for job_id in job_ids:
        assert history[job_id]["status"] == "success"
        assert history[job_id]["success"] is True


def test_voice_tts_disabled_returns_clear_error(monkeypatch):
    import app.api.voice as voice_api

    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False),
        tts_provider=RecordingTTS(),
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)

    response = TestClient(app).post("/api/voice/tts", json={"text": "测试"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "tts_disabled"


def test_voice_tts_provider_failure_does_not_break_chat(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider=FailingTTS(),
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    client = TestClient(app)

    response = client.post("/api/voice/tts", json={"text": "测试"})
    asyncio.run(gateway.wait_for_tts_tasks())
    status = client.get("/api/voice/tts/status").json()
    chat = client.post("/api/chat", json={"session_id": "tts-failure-chat", "message": "有啥"})

    assert response.json()["queued"] is True
    assert status["lastSuccess"] is False
    assert "RuntimeError" in status["lastError"]
    assert chat.status_code == 200
    assert "response" in chat.json()


def test_voice_tts_stop_is_idempotent_preserves_asr_and_allows_new_tts(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    tts = BlockingTTS()
    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    client = TestClient(app)
    session = gateway.session_controller.get_session("stop-session")
    recognizer = FixedFinalASR()
    recognizer.start()
    session.recognizer = recognizer
    session.current_utterance_id = "u-active"
    session.set_status("listening")

    first = client.post("/api/voice/tts", json={"text": "旧播报"}).json()
    assert first["queued"] is True
    assert tts.started.wait(timeout=1)
    second = client.post("/api/voice/tts", json={"text": "待清空播报"}).json()
    assert second["queued"] is True

    stop1 = client.post("/api/voice/tts/stop", json={"session_id": "stop-session"})
    stop2 = client.post("/api/voice/tts/stop", json={"session_id": "stop-session"})

    assert stop1.status_code == 200
    assert stop2.status_code == 200
    assert stop1.json()["ok"] is True
    assert stop2.json()["ok"] is True
    assert stop1.json()["status"]["speaking"] is False
    assert stop1.json()["status"]["queueSize"] == 0
    assert session.recognizer is recognizer
    assert session.current_utterance_id == "u-active"
    assert session.status == "listening"

    third = client.post("/api/voice/tts", json={"text": "新播报"}).json()
    assert third["queued"] is True
    asyncio.run(gateway.wait_for_tts_tasks())
    status = client.get("/api/voice/tts/status").json()
    history = {job["jobId"]: job for job in status["jobHistory"]}

    assert history[first["job_id"]]["status"] == "interrupted"
    assert history[second["job_id"]]["status"] == "interrupted"
    assert history[third["job_id"]]["status"] == "success"
    assert status["lastFinishedJobId"] == third["job_id"]
    assert status["lastSuccess"] is True
    assert status["queueSize"] == 0


def test_websocket_stop_utterance_flushes_final_once(monkeypatch):
    import app.api.voice as voice_api

    orchestrator = CountingOrchestrator()
    text_entry = TextEntryService(store=InMemorySessionStore(), orchestrator=orchestrator)
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False),
        asr_provider_factory=FixedFinalASR,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    monkeypatch.setattr(
        voice_api,
        "evaluate_voice_status",
        lambda *_args, **_kwargs: {"canRecord": True},
    )

    client = TestClient(app)
    with client.websocket_connect("/api/voice/asr?session_id=ws1") as websocket:
        assert websocket.receive_json()["type"] == "status"
        websocket.send_json({"type": "start_utterance", "utterance_id": "u1"})
        assert websocket.receive_json()["status"] == "listening"
        websocket.send_json({"type": "stop_utterance", "utterance_id": "u1"})
        assert websocket.receive_json() == {"type": "final", "utterance_id": "u1", "text": "来一份黑椒牛肉饭"}
        reply = websocket.receive_json()
        assert reply["type"] == "agent_reply"
        assert reply["text"] == "已处理:来一份黑椒牛肉饭"
        tts_status = websocket.receive_json()
        assert tts_status["type"] == "tts_status"
        assert tts_status["utterance_id"] == "u1"
        assert tts_status["source"] == "auto"
        assert tts_status["queued"] is False
        assert tts_status["reason"] == "user_tts_preference_off"
        assert tts_status["job_id"] is None
        assert tts_status["tts_enabled"] is False

        websocket.send_json({"type": "stop_utterance", "utterance_id": "u1"})
        assert websocket.receive_json() == {"type": "duplicate_utterance", "utterance_id": "u1", "ignored": True}
        duplicate_tts_status = websocket.receive_json()
        assert duplicate_tts_status["type"] == "tts_status"
        assert duplicate_tts_status["utterance_id"] == "u1"
        assert duplicate_tts_status["source"] == "auto"
        assert duplicate_tts_status["queued"] is False
        assert duplicate_tts_status["reason"] == "duplicate_utterance"
        assert duplicate_tts_status["job_id"] is None
        assert duplicate_tts_status["tts_enabled"] is False

    assert orchestrator.calls == 1
    assert FixedFinalASR.released is True


def test_websocket_audio_chunk_partial_final_and_agent_reply(monkeypatch):
    import app.api.voice as voice_api

    orchestrator = CountingOrchestrator()
    text_entry = TextEntryService(store=InMemorySessionStore(), orchestrator=orchestrator)
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False),
        asr_provider_factory=ChunkFinalASR,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    monkeypatch.setattr(voice_api, "evaluate_voice_status", lambda *_args, **_kwargs: {"canRecord": True})

    client = TestClient(app)
    with client.websocket_connect("/api/voice/asr?session_id=ws-audio") as websocket:
        assert websocket.receive_json()["type"] == "status"
        websocket.send_json({"type": "start_utterance", "utterance_id": "u-audio"})
        assert websocket.receive_json()["status"] == "listening"
        websocket.send_bytes(b"\x00\x01\x02\x03")
        assert websocket.receive_json() == {"type": "partial", "text": "来一份"}
        websocket.send_json({"type": "stop_utterance", "utterance_id": "u-audio"})
        assert websocket.receive_json() == {"type": "final", "utterance_id": "u-audio", "text": "来一份黑椒牛肉饭"}
        reply = websocket.receive_json()
        tts_status = websocket.receive_json()

    assert reply["type"] == "agent_reply"
    assert reply["text"] == "已处理:来一份黑椒牛肉饭"
    assert tts_status["type"] == "tts_status"
    assert tts_status["reason"] == "user_tts_preference_off"
    assert ChunkFinalASR.chunks == [b"\x00\x01\x02\x03"]
    assert orchestrator.calls == 1


def test_websocket_auto_tts_queues_once_when_preference_enabled(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    tts = RecordingTTS()
    orchestrator = CountingOrchestrator()
    text_entry = TextEntryService(store=InMemorySessionStore(), orchestrator=orchestrator)
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        asr_provider_factory=FixedFinalASR,
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    monkeypatch.setattr(voice_api, "evaluate_voice_status", lambda *_args, **_kwargs: {"canRecord": True})

    client = TestClient(app)
    with client.websocket_connect("/api/voice/asr?session_id=ws-tts") as websocket:
        assert websocket.receive_json()["type"] == "status"
        websocket.send_json({"type": "start_utterance", "utterance_id": "u-tts", "tts_enabled": True})
        assert websocket.receive_json()["status"] == "listening"
        websocket.send_json({"type": "stop_utterance", "utterance_id": "u-tts"})
        assert websocket.receive_json()["type"] == "final"
        assert websocket.receive_json()["type"] == "agent_reply"
        tts_status = websocket.receive_json()

    asyncio.run(gateway.wait_for_tts_tasks())
    status = gateway.tts_status()
    assert tts_status["type"] == "tts_status"
    assert tts_status["utterance_id"] == "u-tts"
    assert tts_status["source"] == "auto"
    assert tts_status["tts_enabled"] is True
    assert tts_status["ok"] is True
    assert tts_status["queued"] is True
    assert tts_status["reason"] is None
    assert tts_status["job_id"] == 1
    assert tts_status["playbackTarget"] == "server"
    assert tts.calls == ["已处理:来一份黑椒牛肉饭"]
    assert status["lastSource"] == "auto"
    assert status["lastSuccess"] is True


def test_websocket_three_auto_tts_rounds_have_job_ids_and_history(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    tts = RecordingTTS()
    orchestrator = CountingOrchestrator()
    text_entry = TextEntryService(store=InMemorySessionStore(), orchestrator=orchestrator)
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        asr_provider_factory=FixedFinalASR,
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    monkeypatch.setattr(voice_api, "evaluate_voice_status", lambda *_args, **_kwargs: {"canRecord": True})

    client = TestClient(app)
    job_ids = []
    with client.websocket_connect("/api/voice/asr?session_id=ws-tts-3") as websocket:
        assert websocket.receive_json()["type"] == "status"
        for index in range(1, 4):
            utterance_id = f"u-tts-{index}"
            websocket.send_json({"type": "start_utterance", "utterance_id": utterance_id, "tts_enabled": True})
            assert websocket.receive_json()["status"] == "listening"
            websocket.send_json({"type": "stop_utterance", "utterance_id": utterance_id})
            final = websocket.receive_json()
            reply = websocket.receive_json()
            tts_status = websocket.receive_json()
            assert final["type"] == "final"
            assert final["utterance_id"] == utterance_id
            assert reply["type"] == "agent_reply"
            assert tts_status["type"] == "tts_status"
            assert tts_status["utterance_id"] == utterance_id
            assert tts_status["queued"] is True
            assert tts_status["job_id"] is not None
            job_ids.append(tts_status["job_id"])

    asyncio.run(gateway.wait_for_tts_tasks())
    status = gateway.tts_status()
    history = {job["jobId"]: job for job in status["jobHistory"]}
    assert len(set(job_ids)) == 3
    for job_id in job_ids:
        assert history[job_id]["status"] == "success"
    assert orchestrator.calls == 3


def test_manual_and_auto_tts_share_app_state_runtime_and_job_history(monkeypatch):
    import asyncio
    import app.api.voice as voice_api

    tts = RecordingTTS()
    orchestrator = CountingOrchestrator()
    text_entry = TextEntryService(store=InMemorySessionStore(), orchestrator=orchestrator)
    gateway = VoiceGatewayAgent(
        text_entry_service=text_entry,
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=True),
        asr_provider_factory=FixedFinalASR,
        tts_provider=tts,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    monkeypatch.setattr(voice_api, "evaluate_voice_status", lambda *_args, **_kwargs: {"canRecord": True})

    client = TestClient(app)
    before = client.get("/api/voice/tts/status").json()
    before_job_ids = {job["jobId"] for job in before["jobHistory"]}

    manual = client.post("/api/voice/tts", json={"text": "测试播报"}).json()
    assert manual["queued"] is True
    assert manual["source"] == "manual"
    asyncio.run(gateway.wait_for_tts_tasks())
    after_manual = client.get("/api/voice/tts/status").json()
    manual_job_ids = {job["jobId"] for job in after_manual["jobHistory"]} - before_job_ids
    assert manual["job_id"] in manual_job_ids

    with client.websocket_connect("/api/voice/asr?session_id=shared-runtime") as websocket:
        assert websocket.receive_json()["type"] == "status"
        websocket.send_json({"type": "start_utterance", "utterance_id": "u-auto-shared", "tts_enabled": True})
        assert websocket.receive_json()["status"] == "listening"
        websocket.send_json({"type": "stop_utterance", "utterance_id": "u-auto-shared"})
        assert websocket.receive_json()["type"] == "final"
        assert websocket.receive_json()["type"] == "agent_reply"
        auto_tts_status = websocket.receive_json()

    assert auto_tts_status["type"] == "tts_status"
    assert auto_tts_status["queued"] is True
    assert auto_tts_status["source"] == "auto"
    assert auto_tts_status["tts_enabled"] is True
    assert auto_tts_status["job_id"] != manual["job_id"]
    asyncio.run(gateway.wait_for_tts_tasks())
    after_auto = client.get("/api/voice/tts/status").json()
    history = {job["jobId"]: job for job in after_auto["jobHistory"]}

    assert before["runtimeId"] == after_manual["runtimeId"] == after_auto["runtimeId"]
    assert after_manual["runnerId"] == after_auto["runnerId"]
    assert history[manual["job_id"]]["source"] == "manual"
    assert history[auto_tts_status["job_id"]]["source"] == "auto"
    assert history[auto_tts_status["job_id"]]["status"] == "success"
    assert after_auto["latestManualJob"]["jobId"] == manual["job_id"]
    assert after_auto["latestAutoJob"]["jobId"] == auto_tts_status["job_id"]


def test_websocket_rejects_when_can_record_false(monkeypatch):
    import app.api.voice as voice_api

    called = {"factory": 0}

    def forbidden_factory():
        called["factory"] += 1
        return FixedFinalASR()

    gateway = VoiceGatewayAgent(
        text_entry_service=TextEntryService(store=InMemorySessionStore(), orchestrator=CountingOrchestrator()),
        session_controller=VoiceSessionController(),
        config=VoiceConfig(voice_enabled=True, tts_enabled=False),
        asr_provider_factory=forbidden_factory,
    )
    voice_api.reset_voice_runtime_for_test(gateway.runtime, gateway)
    monkeypatch.setattr(
        voice_api,
        "evaluate_voice_status",
        lambda *_args, **_kwargs: {
            "canRecord": False,
            "voiceEnabled": False,
            "asrEngine": "vosk",
            "ttsEnabled": True,
            "ttsEngine": "pyttsx3",
            "ttsPlaybackTarget": "server",
            "asrReady": False,
            "ttsReady": False,
            "asrDependencyAvailable": False,
            "ttsDependencyAvailable": False,
            "modelPathExists": False,
            "modelLooksValid": False,
            "modelLoaded": False,
            "canSpeak": False,
            "disabledReason": "后端语音未开启",
            "asrDisabledReason": "ASR 模型路径不存在",
            "ttsDisabledReason": "TTS 依赖缺失",
            "hints": ["请在后端 .env 中设置 VOICE_ENABLED=true"],
            "envFilePath": "D:/project/.env",
            "envFileExists": False,
            "voskModelPath": "./models/asr/vosk-cn",
        },
    )

    client = TestClient(app)
    with client.websocket_connect("/api/voice/asr?session_id=blocked") as websocket:
        first = websocket.receive_json()

    assert first["type"] == "error"
    assert first["code"] == "voice_not_ready"
    assert first["status"]["canRecord"] is False
    assert "voiceEnabled" in first["status"]
    assert called["factory"] == 0


def _poll_tts_status(client: TestClient, finished_target: int, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    last_status = client.get("/api/voice/tts/status").json()
    while time.monotonic() < deadline:
        last_status = client.get("/api/voice/tts/status").json()
        if (
            last_status["jobsFinished"] >= finished_target
            and last_status["queueSize"] == 0
            and last_status["speaking"] is False
        ):
            return last_status
        time.sleep(0.05)
    return last_status


