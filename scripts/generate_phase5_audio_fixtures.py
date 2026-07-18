from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIO_ROOT = ROOT / "evaluation" / "audio"
FIXTURE_ROOT = AUDIO_ROOT / "fixtures"
MANIFEST_ROOT = AUDIO_ROOT / "manifests"
PHASE4_DATA = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
PHASE5_DATA = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"
PHASE5_SCHEMA = ROOT / "evaluation" / "phase5_speech_pipeline.schema.json"

LOCALE_PREFIX = {
    "zh-CN": "ZH",
    "yue-Hant-HK": "YUE",
    "en-HK": "EN",
    "mixed": "MIX",
}

ERROR_CATEGORIES = (
    ("no_speech", "NO_SPEECH", None),
    ("low_confidence", "LOW_CONFIDENCE", None),
    ("truncated_audio", "TRUNCATED", None),
    ("provider_timeout", "PROVIDER_TIMEOUT", None),
    ("provider_error", "PROVIDER_ERROR", None),
    ("unsupported_language", "UNSUPPORTED_LANGUAGE", None),
    ("hash_mismatch", "SUCCESS", "SPEECH_FIXTURE_HASH_MISMATCH"),
    ("malformed_wav", "SUCCESS", "AUDIO_TRUNCATED"),
    ("silence", "SUCCESS", "AUDIO_SILENT"),
    ("too_large", "SUCCESS", "AUDIO_TOO_LARGE"),
    ("unsupported_rate", "SUCCESS", "AUDIO_SAMPLE_RATE_UNSUPPORTED"),
    ("too_short", "SUCCESS", "AUDIO_TOO_SHORT"),
    ("mime_mismatch", "SUCCESS", "AUDIO_CONTENT_TYPE_MISMATCH"),
    ("channels_unsupported", "SUCCESS", "AUDIO_CHANNELS_UNSUPPORTED"),
    ("fixture_not_found", "SUCCESS", "SPEECH_FIXTURE_NOT_FOUND"),
)

LOW_CONFIDENCE_TEXT = {
    "zh-CN": "我要一份鸡腿饭",
    "yue-Hant-HK": "我要一份雞髀飯",
    "en-HK": "Add one chicken leg rice please",
    "mixed": "加 one chicken leg rice",
}

TTS_TEXTS = {
    "zh-CN": (
        "尚未发送给真实餐厅",
        "不代表商家已经接受",
        "模拟人工接管，不是真实人工",
        "存在食品安全风险，不能自动继续",
        "需要重新确认订单",
    ),
    "yue-Hant-HK": (
        "尚未傳送俾真實餐廳",
        "唔代表商家已經接受",
        "模擬人工接管，唔係真人",
        "存在食物安全風險，唔可以自動繼續",
        "需要重新確認訂單",
    ),
    "en-HK": (
        "The order has not been sent to a real restaurant.",
        "This does not mean the merchant has accepted it.",
        "This is a simulated handoff, not a real person.",
        "There is a food safety risk, so the system cannot continue automatically.",
        "The order needs to be confirmed again.",
    ),
}


def jsonl_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def pcm_frames(sample_rate: int, duration_ms: int, seed: int, *, silence: bool = False) -> bytes:
    count = sample_rate * duration_ms // 1000
    frequency = 220 + (seed % 37) * 11
    amplitude = 0 if silence else 700 + (seed % 19) * 30
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate)))
        for i in range(count)
    )


def write_wav(
    path: Path,
    *,
    sample_rate: int,
    duration_ms: int,
    seed: int,
    silence: bool = False,
    channels: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mono = pcm_frames(sample_rate, duration_ms, seed, silence=silence)
    frames = mono if channels == 1 else b"".join(
        mono[index : index + 2] * channels for index in range(0, len(mono), 2)
    )
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(frames)


def write_pcm(path: Path, *, sample_rate: int, duration_ms: int, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pcm_frames(sample_rate, duration_ms, seed))


def audio_details(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as reader:
        duration_ms = reader.getnframes() * 1000 // reader.getframerate()
        return reader.getframerate(), duration_ms


def base_scenario(
    row: dict,
    fixture_id: str,
    audio_path: Path,
    scenario_id: str,
    *,
    content_type: str,
    encoding: str,
    sample_rate_hz: int,
) -> dict:
    entities = row.get("expected_entities") or {}
    return {
        "scenarioId": scenario_id,
        "fixtureId": fixture_id,
        "audioPath": relative(audio_path),
        "sha256": sha256(audio_path),
        "locale": row["locale"],
        "restaurantCode": row["restaurant_code"],
        "branchCode": row["branch_code"],
        "providerMode": "REPLAY",
        "contentType": content_type,
        "encoding": encoding,
        "sampleRateHz": sample_rate_hz,
        "channels": 1,
        "sampleWidthBytes": 2,
        "expectedTranscript": row["input"],
        "expectedDetectedLocale": row["expected_detected_locale"],
        "expectedIntent": row["expected_intent"],
        "expectedClassification": row["expected_classification"],
        "expectedMutation": row["expected_mutation"],
        "expectedItemCode": entities.get("item_code"),
        "expectedQuantity": entities.get("quantity"),
        "expectedHandoffReason": row.get("expected_handoff_reason"),
        "expectedRefusalReason": row.get("expected_refusal_reason"),
        "expectedSpeechOutcome": "SUCCESS",
        "expectedErrorCode": None,
        "expectedDatabaseOrderCount": row.get("expected_database_order_count", 0),
        "setupInputs": row.get("setup_inputs", []),
        "semanticCategory": row["semantic_category"],
        "forbiddenOutcomes": [
            "LIVE_PROVIDER",
            "REAL_CALL",
            "MERCHANT_ACCEPTED",
            "LIVE_LLM",
        ],
        "synthetic": True,
    }


def error_scenario(
    *,
    locale: str,
    index: int,
    category: str,
    provider_outcome: str,
    expected_error: str | None,
    fixture_id: str,
    audio_path: Path,
) -> tuple[dict, dict | None]:
    content_type = "application/octet-stream" if category == "mime_mismatch" else "audio/wav"
    sample_rate = 11025 if category == "unsupported_rate" else 16000
    transcript = LOW_CONFIDENCE_TEXT[locale]
    expected_outcome = {
        "NO_SPEECH": "NO_SPEECH",
        "LOW_CONFIDENCE": "LOW_CONFIDENCE",
        "TRUNCATED": "TRUNCATED",
        "PROVIDER_TIMEOUT": "PROVIDER_TIMEOUT",
        "PROVIDER_ERROR": "PROVIDER_ERROR",
        "UNSUPPORTED_LANGUAGE": "UNSUPPORTED_LANGUAGE",
    }.get(provider_outcome, "VALIDATION_ERROR" if expected_error else "SUCCESS")
    scenario = {
        "scenarioId": f"P5-{LOCALE_PREFIX[locale]}-{index:03d}",
        "fixtureId": fixture_id,
        "audioPath": relative(audio_path),
        "sha256": sha256(audio_path),
        "locale": locale,
        "restaurantCode": "hk-sim-restaurant-a",
        "branchCode": "central",
        "providerMode": "REPLAY",
        "contentType": content_type,
        "encoding": "WAV_PCM_S16LE",
        "sampleRateHz": sample_rate,
        "channels": 2 if category == "channels_unsupported" else 1,
        "sampleWidthBytes": 2,
        "expectedTranscript": transcript if provider_outcome == "LOW_CONFIDENCE" else None,
        "expectedDetectedLocale": None,
        "expectedIntent": None,
        "expectedClassification": "CONFIRM" if provider_outcome in {"LOW_CONFIDENCE", "NO_SPEECH", "TRUNCATED", "PROVIDER_TIMEOUT", "PROVIDER_ERROR"} else None,
        "expectedMutation": False,
        "expectedItemCode": None,
        "expectedQuantity": None,
        "expectedHandoffReason": "LANGUAGE_UNSUPPORTED" if provider_outcome == "UNSUPPORTED_LANGUAGE" else None,
        "expectedRefusalReason": None,
        "expectedSpeechOutcome": expected_outcome,
        "expectedErrorCode": expected_error or {
            "NO_SPEECH": "NO_SPEECH_DETECTED",
            "TRUNCATED": "AUDIO_TRUNCATED",
            "PROVIDER_TIMEOUT": "SPEECH_TIMEOUT",
            "PROVIDER_ERROR": "SPEECH_PROVIDER_FAILURE",
            "UNSUPPORTED_LANGUAGE": "SPEECH_LANGUAGE_UNSUPPORTED",
        }.get(provider_outcome),
        "expectedDatabaseOrderCount": 0,
        "setupInputs": [],
        "semanticCategory": category,
        "forbiddenOutcomes": ["LIVE_PROVIDER", "REAL_CALL", "MERCHANT_ACCEPTED", "LIVE_LLM"],
        "synthetic": True,
    }
    if category == "fixture_not_found":
        return scenario, None
    manifest_hash = sha256(audio_path)
    if category == "hash_mismatch":
        manifest_hash = hashlib.sha256((fixture_id + "-expected").encode()).hexdigest()
    manifest = {
        "fixtureId": fixture_id,
        "audioPath": relative(audio_path),
        "sha256": manifest_hash,
        "transcript": transcript,
        "locale": locale,
        "confidence": 0.20 if provider_outcome == "LOW_CONFIDENCE" else 0.97,
        "confidenceMetadata": {
            "intent_confidence": 0.20 if provider_outcome == "LOW_CONFIDENCE" else 0.97,
            "item_confidence": 0.20 if provider_outcome == "LOW_CONFIDENCE" else 0.97,
            "quantity_confidence": 0.20 if provider_outcome == "LOW_CONFIDENCE" else 0.97,
            "overall_confidence": 0.20 if provider_outcome == "LOW_CONFIDENCE" else 0.97,
        },
        "durationMs": 250,
        "contentType": content_type,
        "encoding": "WAV_PCM_S16LE",
        "sampleRateHz": sample_rate,
        "channels": 2 if category == "channels_unsupported" else 1,
        "sampleWidthBytes": 2,
        "noSpeechProbability": 0.99 if provider_outcome == "NO_SPEECH" else 0.01,
        "outcome": provider_outcome,
        "synthetic": True,
        "generation": "deterministic-tone-fixture",
        "license": "CC0-synthetic-project-generated",
    }
    return scenario, manifest


def schema() -> dict:
    required = [
        "scenarioId", "fixtureId", "audioPath", "sha256", "locale", "restaurantCode", "branchCode", "providerMode",
        "contentType", "encoding", "sampleRateHz", "channels", "sampleWidthBytes",
        "expectedTranscript", "expectedDetectedLocale", "expectedIntent",
        "expectedClassification", "expectedMutation", "expectedItemCode", "expectedQuantity",
        "expectedHandoffReason", "expectedRefusalReason", "expectedSpeechOutcome",
        "expectedErrorCode", "expectedDatabaseOrderCount", "setupInputs", "semanticCategory",
        "forbiddenOutcomes", "synthetic",
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Phase 5 synthetic speech pipeline scenario",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "scenarioId": {"type": "string", "pattern": "^P5-(ZH|YUE|EN|MIX)-[0-9]{3}$"},
            "fixtureId": {"type": "string", "minLength": 1},
            "audioPath": {"type": "string", "minLength": 1},
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "locale": {"enum": list(LOCALE_PREFIX)},
            "restaurantCode": {"type": "string", "minLength": 1},
            "branchCode": {"type": "string", "minLength": 1},
            "providerMode": {"const": "REPLAY"},
            "contentType": {"type": "string"},
            "encoding": {"enum": ["PCM_S16LE", "WAV_PCM_S16LE"]},
            "sampleRateHz": {"type": "integer"},
            "channels": {"type": "integer"},
            "sampleWidthBytes": {"type": "integer"},
            "expectedTranscript": {"type": ["string", "null"]},
            "expectedDetectedLocale": {"type": ["string", "null"]},
            "expectedIntent": {"type": ["string", "null"]},
            "expectedClassification": {"type": ["string", "null"]},
            "expectedMutation": {"type": "boolean"},
            "expectedItemCode": {"type": ["string", "null"]},
            "expectedQuantity": {"type": ["integer", "null"]},
            "expectedHandoffReason": {"type": ["string", "null"]},
            "expectedRefusalReason": {"type": ["string", "null"]},
            "expectedSpeechOutcome": {"type": "string"},
            "expectedErrorCode": {"type": ["string", "null"]},
            "expectedDatabaseOrderCount": {"type": "integer", "minimum": 0},
            "setupInputs": {"type": "array", "items": {"type": "string"}},
            "semanticCategory": {"type": "string"},
            "forbiddenOutcomes": {"type": "array", "items": {"type": "string"}},
            "synthetic": {"const": True},
        },
    }


def main() -> None:
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    phase4 = jsonl_rows(PHASE4_DATA)
    scenarios: list[dict] = []
    asr_manifest: list[dict] = []
    seed = 1
    for locale, prefix in LOCALE_PREFIX.items():
        base_rows = [
            row for row in phase4
            if row["locale"] == locale and row["expression_variant"] == 1
        ]
        if len(base_rows) != 45:
            raise RuntimeError(f"expected 45 Phase 4 base rows for {locale}")
        locale_dir = FIXTURE_ROOT / locale
        for index, row in enumerate(base_rows, 1):
            fixture_id = f"audio-{prefix.casefold()}-{index:03d}"
            raw_pcm = index == 45
            sample_rate_hz = 8000 if raw_pcm else 16000
            encoding = "PCM_S16LE" if raw_pcm else "WAV_PCM_S16LE"
            content_type = "audio/l16" if raw_pcm else "audio/wav"
            path = locale_dir / f"{fixture_id}.{'pcm' if raw_pcm else 'wav'}"
            obsolete_wav = locale_dir / f"{fixture_id}.wav"
            if raw_pcm and obsolete_wav.exists():
                obsolete_wav.unlink()
            if raw_pcm:
                write_pcm(path, sample_rate=sample_rate_hz, duration_ms=250, seed=seed)
            else:
                write_wav(path, sample_rate=sample_rate_hz, duration_ms=250, seed=seed)
            seed += 1
            scenario_id = f"P5-{prefix}-{index:03d}"
            scenarios.append(
                base_scenario(
                    row,
                    fixture_id,
                    path,
                    scenario_id,
                    content_type=content_type,
                    encoding=encoding,
                    sample_rate_hz=sample_rate_hz,
                )
            )
            asr_manifest.append({
                "fixtureId": fixture_id,
                "audioPath": relative(path),
                "sha256": sha256(path),
                "transcript": row["input"],
                "locale": locale,
                "confidence": 0.97,
                "confidenceMetadata": {
                    "intent_confidence": 0.97,
                    "item_confidence": 0.97,
                    "quantity_confidence": 0.97,
                    "modifier_confidence": 0.97,
                    "address_confidence": 0.97,
                    "phone_confidence": 0.97,
                    "overall_confidence": 0.97,
                },
                "durationMs": 250,
                "contentType": content_type,
                "encoding": encoding,
                "sampleRateHz": sample_rate_hz,
                "channels": 1,
                "sampleWidthBytes": 2,
                "noSpeechProbability": 0.01,
                "outcome": "SUCCESS",
                "synthetic": True,
                "generation": "deterministic-tone-fixture",
                "license": "CC0-synthetic-project-generated",
            })

        invalid_dir = FIXTURE_ROOT / "invalid" / locale
        for offset, (category, provider_outcome, expected_error) in enumerate(ERROR_CATEGORIES, 46):
            fixture_id = f"audio-{prefix.casefold()}-{offset:03d}"
            path = invalid_dir / f"{fixture_id}.wav"
            if category == "malformed_wav":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"RIFF" + struct.pack("<I", 32 + seed) + b"WAVEfmt " + bytes([seed % 251]))
            elif category == "silence":
                write_wav(path, sample_rate=16000, duration_ms=250 + seed % 17, seed=seed, silence=True)
            elif category == "too_large":
                write_wav(path, sample_rate=16000, duration_ms=30001, seed=seed)
            elif category == "unsupported_rate":
                write_wav(path, sample_rate=11025, duration_ms=250, seed=seed)
            elif category == "too_short":
                write_wav(path, sample_rate=16000, duration_ms=50, seed=seed)
            elif category == "channels_unsupported":
                write_wav(path, sample_rate=16000, duration_ms=250, seed=seed, channels=2)
            else:
                write_wav(path, sample_rate=16000, duration_ms=250, seed=seed)
            seed += 1
            scenario, manifest = error_scenario(
                locale=locale,
                index=offset,
                category=category,
                provider_outcome=provider_outcome,
                expected_error=expected_error,
                fixture_id=fixture_id,
                audio_path=path,
            )
            scenarios.append(scenario)
            if manifest:
                asr_manifest.append(manifest)

    tts_manifest: list[dict] = []
    tts_dir = FIXTURE_ROOT / "tts"
    for locale, texts in TTS_TEXTS.items():
        for index, text in enumerate(texts, 1):
            path = tts_dir / locale / f"tts-{LOCALE_PREFIX[locale].casefold()}-{index:02d}.wav"
            write_wav(path, sample_rate=16000, duration_ms=300, seed=seed)
            seed += 1
            tts_manifest.append({
                "messageKey": f"safety-{LOCALE_PREFIX[locale].casefold()}-{index:02d}",
                "text": text,
                "textSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "locale": locale,
                "voiceId": "replay-neutral",
                "encoding": "WAV_PCM_S16LE",
                "sampleRateHz": 16000,
                "durationMs": 300,
                "audioPath": relative(path),
                "sha256": sha256(path),
                "synthetic": True,
                "generation": "deterministic-tone-fixture",
                "license": "CC0-synthetic-project-generated",
            })

    PHASE5_DATA.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in scenarios),
        encoding="utf-8",
    )
    PHASE5_SCHEMA.write_text(json.dumps(schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (MANIFEST_ROOT / "phase5_asr_manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in asr_manifest),
        encoding="utf-8",
    )
    (MANIFEST_ROOT / "phase5_tts_manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in tts_manifest),
        encoding="utf-8",
    )
    print(f"generated {len(scenarios)} scenarios, {len(asr_manifest)} ASR entries, {len(tts_manifest)} TTS entries")


if __name__ == "__main__":
    main()
