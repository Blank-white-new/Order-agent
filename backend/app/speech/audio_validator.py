from __future__ import annotations

import struct
from dataclasses import dataclass

from app.speech.config import SpeechSettings
from app.speech.contracts import AudioInput
from app.speech.errors import speech_error
from app.speech.formats import (
    PCM_CONTENT_TYPES,
    SUPPORTED_ENCODINGS,
    WAV_CONTENT_TYPES,
    AudioEncoding,
)


MAX_METADATA_BYTES = 65_536
MAX_CHUNKS = 128


@dataclass(frozen=True)
class AudioValidationResult:
    encoding: AudioEncoding
    content_type: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    duration_ms: int
    pcm_payload: bytes


class AudioValidator:
    """Strict validator for mono PCM S16LE and its RIFF/WAVE container."""

    def __init__(self, settings: SpeechSettings) -> None:
        self.settings = settings

    def validate(self, audio: AudioInput) -> AudioValidationResult:
        if audio.encoding not in SUPPORTED_ENCODINGS:
            raise speech_error("AUDIO_ENCODING_UNSUPPORTED")
        if len(audio.payload) > self.settings.max_audio_bytes:
            raise speech_error("AUDIO_TOO_LARGE")
        if not audio.payload:
            raise speech_error("AUDIO_EMPTY")
        if audio.channels != 1:
            raise speech_error("AUDIO_CHANNELS_UNSUPPORTED")
        if audio.sample_rate_hz not in self.settings.supported_sample_rates_hz:
            raise speech_error("AUDIO_SAMPLE_RATE_UNSUPPORTED")
        if audio.sample_width_bytes != 2:
            raise speech_error("AUDIO_SAMPLE_WIDTH_UNSUPPORTED")
        content_type = audio.content_type.split(";", 1)[0].strip().casefold()
        if audio.encoding == AudioEncoding.WAV_PCM_S16LE:
            if content_type not in WAV_CONTENT_TYPES:
                raise speech_error("AUDIO_CONTENT_TYPE_MISMATCH")
            return self._validate_wav(audio, content_type)
        if content_type not in PCM_CONTENT_TYPES or audio.payload.startswith(b"RIFF"):
            raise speech_error("AUDIO_CONTENT_TYPE_MISMATCH")
        return self._validate_pcm(audio, content_type)

    def _validate_pcm(self, audio: AudioInput, content_type: str) -> AudioValidationResult:
        if len(audio.payload) % 2:
            raise speech_error("AUDIO_TRUNCATED")
        return self._validate_frames(
            audio=audio,
            content_type=content_type,
            pcm_payload=audio.payload,
            sample_rate_hz=audio.sample_rate_hz,
            channels=audio.channels,
            sample_width_bytes=audio.sample_width_bytes,
        )

    def _validate_wav(self, audio: AudioInput, content_type: str) -> AudioValidationResult:
        payload = audio.payload
        if len(payload) < 12:
            raise speech_error("AUDIO_TRUNCATED")
        if payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
            raise speech_error("AUDIO_CONTAINER_INVALID")
        declared_size = struct.unpack_from("<I", payload, 4)[0] + 8
        if declared_size > len(payload):
            raise speech_error("AUDIO_TRUNCATED")
        if declared_size != len(payload):
            raise speech_error("AUDIO_CONTAINER_INVALID")

        offset = 12
        fmt: tuple[int, int, int, int, int, int] | None = None
        pcm_payload: bytes | None = None
        metadata_bytes = 0
        chunks = 0
        while offset < len(payload):
            chunks += 1
            if chunks > MAX_CHUNKS:
                raise speech_error("AUDIO_CONTAINER_INVALID")
            if len(payload) - offset < 8:
                raise speech_error("AUDIO_TRUNCATED")
            chunk_id = payload[offset : offset + 4]
            if any(byte < 0x20 or byte > 0x7E for byte in chunk_id):
                raise speech_error("AUDIO_CONTAINER_INVALID")
            chunk_size = struct.unpack_from("<I", payload, offset + 4)[0]
            body_start = offset + 8
            body_end = body_start + chunk_size
            padded_end = body_end + (chunk_size & 1)
            if body_end > len(payload) or padded_end > len(payload):
                raise speech_error("AUDIO_TRUNCATED")
            body = payload[body_start:body_end]
            if chunk_id == b"fmt ":
                if fmt is not None or chunk_size != 16:
                    raise speech_error("AUDIO_CONTAINER_INVALID")
                fmt = struct.unpack("<HHIIHH", body)
            elif chunk_id == b"data":
                if pcm_payload is not None:
                    raise speech_error("AUDIO_CONTAINER_INVALID")
                pcm_payload = body
            else:
                metadata_bytes += chunk_size
                if metadata_bytes > MAX_METADATA_BYTES:
                    raise speech_error("AUDIO_CONTAINER_INVALID")
            offset = padded_end

        if fmt is None or pcm_payload is None:
            raise speech_error("AUDIO_CONTAINER_INVALID")
        audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = fmt
        if audio_format != 1:
            raise speech_error("AUDIO_ENCODING_UNSUPPORTED")
        if channels != 1:
            raise speech_error("AUDIO_CHANNELS_UNSUPPORTED")
        if sample_rate not in self.settings.supported_sample_rates_hz:
            raise speech_error("AUDIO_SAMPLE_RATE_UNSUPPORTED")
        if bits_per_sample != 16 or block_align != 2:
            raise speech_error("AUDIO_SAMPLE_WIDTH_UNSUPPORTED")
        if byte_rate != sample_rate * block_align:
            raise speech_error("AUDIO_CONTAINER_INVALID")
        if (
            audio.channels != channels
            or audio.sample_rate_hz != sample_rate
            or audio.sample_width_bytes * 8 != bits_per_sample
        ):
            raise speech_error("AUDIO_CONTAINER_INVALID")
        if len(pcm_payload) % block_align:
            raise speech_error("AUDIO_TRUNCATED")
        return self._validate_frames(
            audio=audio,
            content_type=content_type,
            pcm_payload=pcm_payload,
            sample_rate_hz=sample_rate,
            channels=channels,
            sample_width_bytes=bits_per_sample // 8,
        )

    def _validate_frames(
        self,
        *,
        audio: AudioInput,
        content_type: str,
        pcm_payload: bytes,
        sample_rate_hz: int,
        channels: int,
        sample_width_bytes: int,
    ) -> AudioValidationResult:
        if not pcm_payload:
            raise speech_error("AUDIO_EMPTY")
        if not any(pcm_payload):
            raise speech_error("AUDIO_SILENT")
        frame_width = channels * sample_width_bytes
        if len(pcm_payload) % frame_width:
            raise speech_error("AUDIO_TRUNCATED")
        frame_count = len(pcm_payload) // frame_width
        duration_ms = (frame_count * 1000) // sample_rate_hz
        if duration_ms < self.settings.min_duration_ms:
            raise speech_error("AUDIO_TOO_SHORT")
        if duration_ms > self.settings.max_duration_ms:
            raise speech_error("AUDIO_TOO_LONG")
        return AudioValidationResult(
            encoding=audio.encoding,
            content_type=content_type,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            sample_width_bytes=sample_width_bytes,
            frame_count=frame_count,
            duration_ms=duration_ms,
            pcm_payload=pcm_payload,
        )
