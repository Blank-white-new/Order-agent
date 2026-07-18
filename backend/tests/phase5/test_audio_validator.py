from __future__ import annotations

import io
import struct
import wave

import pytest

from app.speech.audio_validator import AudioValidator
from app.speech.config import SpeechSettings
from app.speech.contracts import AudioInput
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding


def wav_bytes(
    *,
    sample_rate: int = 16_000,
    duration_ms: int = 200,
    channels: int = 1,
    width: int = 2,
    silence: bool = False,
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(sample_rate)
        frames = sample_rate * duration_ms // 1000
        sample = b"\x00" * width if silence else ((100).to_bytes(width, "little", signed=True))
        writer.writeframes(sample * channels * frames)
    return output.getvalue()


def audio(payload: bytes, **changes) -> AudioInput:
    values = {
        "payload": payload,
        "content_type": "audio/wav",
        "encoding": AudioEncoding.WAV_PCM_S16LE,
        "sample_rate_hz": 16_000,
        "channels": 1,
        "sample_width_bytes": 2,
        "fixture_id": "unit-audio",
        "synthetic": True,
    }
    values.update(changes)
    return AudioInput(**values)


@pytest.fixture
def validator():
    return AudioValidator(
        SpeechSettings(app_env="test", simulation_enabled=True, asr_provider="replay")
    )


def assert_code(validator: AudioValidator, value: AudioInput, code: str) -> None:
    with pytest.raises(SpeechError) as raised:
        validator.validate(value)
    assert raised.value.code == code


@pytest.mark.parametrize("sample_rate", [8_000, 16_000])
def test_accepts_supported_wav_and_raw_pcm(validator, sample_rate):
    payload = wav_bytes(sample_rate=sample_rate)
    result = validator.validate(audio(payload, sample_rate_hz=sample_rate))
    assert result.sample_rate_hz == sample_rate
    assert result.channels == 1
    assert result.sample_width_bytes == 2
    raw = result.pcm_payload
    raw_result = validator.validate(
        audio(
            raw,
            content_type="audio/L16",
            encoding=AudioEncoding.PCM_S16LE,
            sample_rate_hz=sample_rate,
        )
    )
    assert raw_result.pcm_payload == raw


def test_rejects_empty_silent_short_and_oversized_audio(validator):
    assert_code(validator, audio(b""), "AUDIO_EMPTY")
    assert_code(validator, audio(wav_bytes(silence=True)), "AUDIO_SILENT")
    assert_code(validator, audio(wav_bytes(duration_ms=50)), "AUDIO_TOO_SHORT")
    assert_code(validator, audio(b"x" * (validator.settings.max_audio_bytes + 1)), "AUDIO_TOO_LARGE")


def test_rejects_channel_rate_width_encoding_and_mime_mismatches(validator):
    assert_code(
        validator,
        audio(wav_bytes(channels=2), channels=2),
        "AUDIO_CHANNELS_UNSUPPORTED",
    )
    assert_code(
        validator,
        audio(wav_bytes(sample_rate=11_025), sample_rate_hz=11_025),
        "AUDIO_SAMPLE_RATE_UNSUPPORTED",
    )
    assert_code(
        validator,
        audio(wav_bytes(width=1), sample_width_bytes=1),
        "AUDIO_SAMPLE_WIDTH_UNSUPPORTED",
    )
    assert_code(
        validator,
        audio(wav_bytes(), encoding=AudioEncoding.MP3),
        "AUDIO_ENCODING_UNSUPPORTED",
    )
    assert_code(
        validator,
        audio(wav_bytes(), content_type="audio/mpeg"),
        "AUDIO_CONTENT_TYPE_MISMATCH",
    )


def test_rejects_invalid_riff_lengths_chunks_and_control_ids(validator):
    payload = bytearray(wav_bytes())
    struct.pack_into("<I", payload, 4, len(payload) + 50)
    assert_code(validator, audio(bytes(payload)), "AUDIO_TRUNCATED")

    payload = bytearray(wav_bytes())
    payload[12:16] = b"\x00mt "
    assert_code(validator, audio(bytes(payload)), "AUDIO_CONTAINER_INVALID")

    payload = bytearray(wav_bytes())
    payload[20:22] = (3).to_bytes(2, "little")
    assert_code(validator, audio(bytes(payload)), "AUDIO_ENCODING_UNSUPPORTED")


def test_rejects_unknown_metadata_above_bound(validator):
    original = wav_bytes()
    metadata = b"JUNK" + struct.pack("<I", 65_538) + b"x" * 65_538
    payload = bytearray(original[:12] + metadata + original[12:])
    struct.pack_into("<I", payload, 4, len(payload) - 8)
    assert_code(validator, audio(bytes(payload)), "AUDIO_CONTAINER_INVALID")
