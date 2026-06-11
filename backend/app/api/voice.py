from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.agents.voice_gateway_agent import VoiceGatewayAgent
from app.runtime import text_entry_service, voice_runtime
from app.voice.debug import log_auto_tts_debug
from app.voice.runtime import VoiceRuntime
from app.voice.status import evaluate_voice_status


router = APIRouter()
logger = logging.getLogger(__name__)
# Kept only to avoid breaking old imports. Runtime paths must use app.state via get_voice_runtime/get_voice_gateway.
voice_gateway: VoiceGatewayAgent | None = None


class VoiceTTSRequest(BaseModel):
    text: str
    session_id: str = "voice-tts"


@router.get("/voice/status")
def voice_status(request: Request) -> dict[str, Any]:
    runtime = get_voice_runtime(request)
    return evaluate_voice_status(runtime.config)


@router.post("/voice/tts")
async def voice_tts(request: Request, payload: VoiceTTSRequest) -> dict[str, Any]:
    runtime = get_voice_runtime(request)
    return runtime.queue_manual_tts(payload.text)


@router.get("/voice/tts/status")
def voice_tts_status(request: Request) -> dict[str, Any]:
    runtime = get_voice_runtime(request)
    return runtime.tts_status()


@router.websocket("/voice/asr")
async def voice_asr(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    runtime = get_voice_runtime(websocket)
    gateway = get_voice_gateway(websocket, runtime)
    initial_status = evaluate_voice_status(runtime.config)
    if not initial_status["canRecord"]:
        await websocket.send_json(_voice_not_ready_event(initial_status))
        await websocket.close()
        return

    start_event = gateway.start_session(session_id)
    await websocket.send_json(start_event)
    if start_event.get("type") == "error":
        return

    async def emit(event: dict[str, Any]) -> None:
        await websocket.send_json(event)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                for event in await gateway.on_audio_chunk(session_id, message["bytes"]):
                    await websocket.send_json(event)
                continue
            if message.get("text") is None:
                continue

            payload = json.loads(message["text"])
            message_type = payload.get("type")
            utterance_id = payload.get("utterance_id", "")
            if message_type == "start_utterance":
                current_status = evaluate_voice_status(runtime.config)
                if not current_status["canRecord"]:
                    await websocket.send_json(_voice_not_ready_event(current_status))
                    continue
                await websocket.send_json(
                    gateway.begin_utterance(
                        session_id,
                        utterance_id,
                        tts_enabled=payload.get("tts_enabled"),
                    )
                )
            elif message_type == "stop_utterance":
                events = await gateway.stop_utterance(session_id, utterance_id, emit=emit)
                for event in events:
                    try:
                        await websocket.send_json(event)
                        if event.get("type") == "tts_status":
                            log_auto_tts_debug(
                                logger,
                                runtime.config,
                                "tts_status_send_result",
                                session_id=session_id,
                                utterance_id=event.get("utterance_id"),
                                queued=event.get("queued"),
                                reason=event.get("reason"),
                                job_id=event.get("job_id"),
                                tts_enabled=event.get("tts_enabled"),
                                send_ok=True,
                            )
                    except Exception as exc:
                        if event.get("type") == "tts_status":
                            logger.warning(
                                "voice websocket warning: send_tts_status_failed, utterance_id=%s, job_id=%s, queued=%s, error=%s: %s",
                                event.get("utterance_id"),
                                event.get("job_id"),
                                event.get("queued"),
                                type(exc).__name__,
                                exc,
                            )
                            log_auto_tts_debug(
                                logger,
                                runtime.config,
                                "send_tts_status_failed",
                                session_id=session_id,
                                utterance_id=event.get("utterance_id"),
                                queued=event.get("queued"),
                                reason=event.get("reason"),
                                job_id=event.get("job_id"),
                                tts_enabled=event.get("tts_enabled"),
                                send_ok=False,
                                error=type(exc).__name__,
                            )
                        else:
                            raise
            else:
                await websocket.send_json({"type": "error", "message": f"未知语音消息类型: {message_type}"})
    except WebSocketDisconnect:
        gateway.stop_session(session_id)
    finally:
        gateway.stop_session(session_id)


def get_voice_runtime(scope_owner: Request | WebSocket) -> VoiceRuntime:
    runtime = getattr(scope_owner.app.state, "voice_runtime", None)
    if runtime is None:
        scope_owner.app.state.voice_runtime = voice_runtime
        runtime = voice_runtime
    return runtime


def get_voice_gateway(scope_owner: Request | WebSocket, runtime: VoiceRuntime | None = None) -> VoiceGatewayAgent:
    gateway = getattr(scope_owner.app.state, "voice_gateway", None)
    runtime = runtime or get_voice_runtime(scope_owner)
    if gateway is None or getattr(gateway, "runtime", None) is not runtime:
        gateway = VoiceGatewayAgent(text_entry_service=text_entry_service, config=runtime.config, runtime=runtime)
        scope_owner.app.state.voice_gateway = gateway
    return gateway


def reset_voice_runtime_for_test(runtime: VoiceRuntime, gateway: VoiceGatewayAgent | None = None) -> None:
    from app.main import app

    app.state.voice_runtime = runtime
    app.state.voice_gateway = gateway or VoiceGatewayAgent(text_entry_service=text_entry_service, config=runtime.config, runtime=runtime)


def _voice_not_ready_event(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "error",
        "code": "voice_not_ready",
        "message": status.get("disabledReason") or status.get("asrDisabledReason") or "语音输入未就绪",
        "status": status,
    }
