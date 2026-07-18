from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.runtime import speech_pipeline_service, speech_registry, speech_settings
from app.speech.contracts import AudioInput
from app.speech.errors import speech_error
from app.speech.formats import AudioEncoding


router = APIRouter(prefix="/speech", tags=["synthetic-speech"])


class SynthesisBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    locale: str
    voice_id: str = Field(default="replay-neutral", alias="voiceId")
    sample_rate_hz: int = Field(default=16_000, alias="sampleRateHz")
    output_encoding: AudioEncoding = Field(default=AudioEncoding.WAV_PCM_S16LE, alias="outputEncoding")


def _require_enabled() -> None:
    if not speech_settings.may_use_simulation:
        raise speech_error("SPEECH_SIMULATION_DISABLED")


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > speech_settings.max_audio_bytes:
                raise speech_error("AUDIO_TOO_LARGE")
        except ValueError as exc:
            raise speech_error("AUDIO_CONTAINER_INVALID") from exc
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > speech_settings.max_audio_bytes:
            raise speech_error("AUDIO_TOO_LARGE")
        chunks.append(chunk)
    payload = b"".join(chunks)
    if not payload:
        raise speech_error("AUDIO_EMPTY")
    return payload


def _audio_input(
    payload: bytes,
    content_type: str | None,
    fixture_id: str,
    encoding: AudioEncoding,
    sample_rate_hz: int,
    channels: int,
    sample_width_bytes: int,
) -> AudioInput:
    return AudioInput(
        payload=payload,
        content_type=content_type or "application/octet-stream",
        encoding=encoding,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        sample_width_bytes=sample_width_bytes,
        fixture_id=fixture_id,
        synthetic=True,
    )


@router.get("/capabilities")
def capabilities() -> dict:
    _require_enabled()
    return speech_registry.list_capabilities()


@router.get("/fixtures")
def fixtures() -> dict:
    _require_enabled()
    return {
        "simulation": True,
        "providerMode": "REPLAY",
        "realSpeechRecognition": False,
        "fixtures": speech_registry.list_replay_fixtures(),
    }


@router.get("/fixtures/{fixture_id}/audio")
def fixture_audio(fixture_id: str) -> Response:
    _require_enabled()
    payload, content_type = speech_registry.get_replay_fixture_audio(fixture_id)
    return Response(
        content=payload,
        media_type=content_type,
        headers={
            "X-Simulation": "true",
            "X-Provider-Mode": "REPLAY",
            "X-Real-Speech-Recognition": "false",
        },
    )


@router.post("/transcribe")
async def transcribe(
    request: Request,
    fixture_id: Annotated[str, Header(alias="X-Fixture-Id")],
    session_id: Annotated[str, Header(alias="X-Session-Id")],
    restaurant_code: Annotated[str, Header(alias="X-Restaurant-Code")],
    branch_code: Annotated[str, Header(alias="X-Branch-Code")],
    encoding: Annotated[AudioEncoding, Header(alias="X-Audio-Encoding")] = AudioEncoding.WAV_PCM_S16LE,
    sample_rate_hz: Annotated[int, Header(alias="X-Sample-Rate-Hz")] = 16_000,
    channels: Annotated[int, Header(alias="X-Channels")] = 1,
    sample_width_bytes: Annotated[int, Header(alias="X-Sample-Width-Bytes")] = 2,
    locale_hint: Annotated[str | None, Header(alias="X-Locale-Hint")] = None,
) -> dict:
    _require_enabled()
    payload = await _bounded_body(request)
    transcript, validated, trace_id = speech_pipeline_service.transcribe(
        session_id=session_id,
        restaurant_code=restaurant_code,
        branch_code=branch_code,
        audio=_audio_input(
            payload,
            request.headers.get("content-type"),
            fixture_id,
            encoding,
            sample_rate_hz,
            channels,
            sample_width_bytes,
        ),
        locale_hint=locale_hint,
    )
    return {
        "simulation": True,
        "providerMode": "REPLAY",
        "realSpeechRecognition": False,
        "realSpeechSynthesis": False,
        "traceId": trace_id,
        "audio": {
            "durationMs": validated.duration_ms,
            "sampleRateHz": validated.sample_rate_hz,
            "channels": validated.channels,
            "sampleWidthBytes": validated.sample_width_bytes,
        },
        **transcript.serializable(include_transcript=True),
    }


@router.post("/respond")
async def respond(
    request: Request,
    fixture_id: Annotated[str, Header(alias="X-Fixture-Id")],
    session_id: Annotated[str, Header(alias="X-Session-Id")],
    restaurant_code: Annotated[str, Header(alias="X-Restaurant-Code")],
    branch_code: Annotated[str, Header(alias="X-Branch-Code")],
    encoding: Annotated[AudioEncoding, Header(alias="X-Audio-Encoding")] = AudioEncoding.WAV_PCM_S16LE,
    sample_rate_hz: Annotated[int, Header(alias="X-Sample-Rate-Hz")] = 16_000,
    channels: Annotated[int, Header(alias="X-Channels")] = 1,
    sample_width_bytes: Annotated[int, Header(alias="X-Sample-Width-Bytes")] = 2,
    locale_hint: Annotated[str | None, Header(alias="X-Locale-Hint")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    synthesize_response: Annotated[bool, Query(alias="synthesizeResponse")] = False,
) -> dict:
    _require_enabled()
    payload = await _bounded_body(request)
    result = await speech_pipeline_service.handle_audio_message(
        session_id=session_id,
        restaurant_code=restaurant_code,
        branch_code=branch_code,
        audio=_audio_input(
            payload,
            request.headers.get("content-type"),
            fixture_id,
            encoding,
            sample_rate_hz,
            channels,
            sample_width_bytes,
        ),
        locale_hint=locale_hint,
        idempotency_key=idempotency_key,
        synthesize_response=synthesize_response,
    )
    return result.serializable(include_transcript=True)


@router.post("/synthesize")
def synthesize(
    body: SynthesisBody,
    session_id: Annotated[str, Header(alias="X-Session-Id")],
    restaurant_code: Annotated[str, Header(alias="X-Restaurant-Code")],
    branch_code: Annotated[str, Header(alias="X-Branch-Code")],
) -> Response:
    _require_enabled()
    result = speech_pipeline_service.synthesize(
        text=body.text,
        locale=body.locale,
        voice_id=body.voice_id,
        output_encoding=body.output_encoding,
        sample_rate_hz=body.sample_rate_hz,
        session_id=session_id,
        restaurant_code=restaurant_code,
        branch_code=branch_code,
    )
    return Response(
        content=result.payload,
        media_type=result.content_type,
        headers={
            "X-Simulation": "true",
            "X-Provider-Mode": "REPLAY",
            "X-Real-Speech-Synthesis": "false",
            "X-Audio-Encoding": result.encoding.value,
            "X-Sample-Rate-Hz": str(result.sample_rate_hz),
            "X-Duration-Ms": str(result.duration_ms),
        },
    )
