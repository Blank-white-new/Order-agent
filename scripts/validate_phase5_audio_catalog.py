from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.speech.audio_validator import AudioValidator  # noqa: E402
from app.speech.config import SpeechSettings  # noqa: E402
from app.speech.contracts import AudioInput  # noqa: E402
from app.speech.errors import SpeechError  # noqa: E402
from app.speech.formats import AudioEncoding  # noqa: E402


DATA_PATH = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"
SCHEMA_PATH = ROOT / "evaluation" / "phase5_speech_pipeline.schema.json"
ASR_MANIFEST_PATH = ROOT / "evaluation" / "audio" / "manifests" / "phase5_asr_manifest.jsonl"
TTS_MANIFEST_PATH = ROOT / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl"
ALLOWED_ROOT = (ROOT / "evaluation" / "audio" / "fixtures").resolve()
LOCALES = {"zh-CN", "yue-Hant-HK", "en-HK", "mixed"}
SENSITIVE_PATTERNS = (
    re.compile(r"(?:api[_ -]?key|provider[_ -]?secret)\s*[:=]", re.I),
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"(?:\+?852[- ]?)?[569]\d{3}[- ]?\d{4}"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
)
VALIDATION_ERRORS = {
    "AUDIO_CONTAINER_INVALID",
    "AUDIO_TRUNCATED",
    "AUDIO_SILENT",
    "AUDIO_TOO_LARGE",
    "AUDIO_SAMPLE_RATE_UNSUPPORTED",
    "AUDIO_TOO_SHORT",
    "AUDIO_CONTENT_TYPE_MISMATCH",
    "AUDIO_EMPTY",
    "AUDIO_CHANNELS_UNSUPPORTED",
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError(f"{path.name}:{line_number} is not an object")
        rows.append(value)
    return rows


def safe_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise AssertionError(f"unsafe fixture path: {relative!r}")
    candidate = (ROOT / Path(*pure.parts)).resolve()
    candidate.relative_to(ALLOWED_ROOT)
    if not candidate.is_file():
        raise AssertionError(f"fixture missing: {relative}")
    return candidate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audio_input(row: dict, path: Path) -> AudioInput:
    return AudioInput(
        payload=path.read_bytes(),
        content_type=row["contentType"],
        encoding=AudioEncoding(row["encoding"]),
        sample_rate_hz=int(row["sampleRateHz"]),
        channels=int(row["channels"]),
        sample_width_bytes=int(row["sampleWidthBytes"]),
        fixture_id=row["fixtureId"],
        synthetic=True,
    )


def validate() -> dict:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if schema.get("type") != "object" or not schema.get("required"):
        raise AssertionError("Phase 5 schema is incomplete")
    required = set(schema["required"])
    scenarios = load_jsonl(DATA_PATH)
    asr_rows = load_jsonl(ASR_MANIFEST_PATH)
    tts_rows = load_jsonl(TTS_MANIFEST_PATH)
    if len(scenarios) < 240:
        raise AssertionError("Phase 5 requires at least 240 scenarios")
    ids = [row.get("scenarioId") for row in scenarios]
    fixture_ids = [row.get("fixtureId") for row in scenarios]
    if len(ids) != len(set(ids)) or None in ids:
        raise AssertionError("scenario IDs must be present and unique")
    if len(fixture_ids) != len(set(fixture_ids)) or None in fixture_ids:
        raise AssertionError("fixture IDs must be present and unique")
    locale_counts = Counter(row.get("locale") for row in scenarios)
    if set(locale_counts) != LOCALES or any(locale_counts[locale] < 60 for locale in LOCALES):
        raise AssertionError(f"invalid locale counts: {locale_counts}")

    settings = SpeechSettings(
        app_env="test",
        simulation_data_only=True,
        asr_provider="replay",
        tts_provider="replay",
        simulation_enabled=True,
    )
    validator = AudioValidator(settings)
    path_by_fixture: dict[str, Path] = {}
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    for row in scenarios:
        missing = required - set(row)
        if missing:
            raise AssertionError(f"{row.get('scenarioId')} missing fields: {sorted(missing)}")
        if row["providerMode"] != "REPLAY" or row["synthetic"] is not True:
            raise AssertionError("all Phase 5 scenarios must be synthetic replay")
        review_text = json.dumps(
            {
                "expectedTranscript": row.get("expectedTranscript"),
                "setupInputs": row.get("setupInputs"),
                "audioPath": row.get("audioPath"),
            },
            ensure_ascii=False,
        )
        # The Phase 4 catalog's only phone token is this documented fictional
        # fixture number; remove it before scanning for accidental real data.
        review_text = review_text.replace("55550101", "[synthetic-phone]")
        if any(pattern.search(review_text) for pattern in SENSITIVE_PATTERNS):
            raise AssertionError(f"sensitive-looking data in {row['scenarioId']}")
        path = safe_path(row["audioPath"])
        actual = digest(path)
        if actual != row["sha256"]:
            raise AssertionError(f"dataset hash mismatch: {row['scenarioId']}")
        path_by_fixture[row["fixtureId"]] = path
        hashes[actual].append(row["fixtureId"])
        error = row["expectedErrorCode"]
        if error in VALIDATION_ERRORS and row["semanticCategory"] != "truncated_audio":
            try:
                validator.validate(audio_input(row, path))
            except SpeechError as exc:
                if exc.code != error:
                    raise AssertionError(
                        f"{row['scenarioId']} expected {error}, got {exc.code}"
                    ) from exc
            else:
                raise AssertionError(f"{row['scenarioId']} did not fail validation")
        elif error not in {"SPEECH_FIXTURE_NOT_FOUND", "SPEECH_FIXTURE_HASH_MISMATCH"}:
            validator.validate(audio_input(row, path))
        if (
            error is None
            and row["expectedSpeechOutcome"] == "SUCCESS"
            and "/invalid/" in f"/{row['audioPath']}"
        ):
            raise AssertionError("normal scenario references invalid directory")
    duplicates = {value: ids for value, ids in hashes.items() if len(ids) > 1}
    if duplicates:
        raise AssertionError(f"duplicate fixture content: {duplicates}")

    scenarios_by_fixture = {row["fixtureId"]: row for row in scenarios}
    transcript_by_hash: dict[str, str] = {}
    asr_ids = set()
    for row in asr_rows:
        fixture_id = row.get("fixtureId")
        if not fixture_id or fixture_id in asr_ids:
            raise AssertionError("ASR manifest fixture IDs must be unique")
        asr_ids.add(fixture_id)
        scenario = scenarios_by_fixture.get(fixture_id)
        if scenario is None:
            raise AssertionError(f"orphan ASR manifest entry: {fixture_id}")
        if row.get("synthetic") is not True or not row.get("generation") or not row.get("license"):
            raise AssertionError(f"ASR provenance missing: {fixture_id}")
        manifest_path = safe_path(row["audioPath"])
        if manifest_path != path_by_fixture[fixture_id]:
            raise AssertionError(f"ASR path mismatch: {fixture_id}")
        actual = digest(manifest_path)
        if scenario["expectedErrorCode"] == "SPEECH_FIXTURE_HASH_MISMATCH":
            if row["sha256"] == actual:
                raise AssertionError("negative hash fixture unexpectedly matches")
        elif row["sha256"] != actual:
            raise AssertionError(f"ASR manifest hash mismatch: {fixture_id}")
        old = transcript_by_hash.setdefault(row["sha256"], row.get("transcript", ""))
        if old != row.get("transcript", ""):
            raise AssertionError("one ASR hash maps to conflicting transcripts")
    missing_manifest = {
        row["fixtureId"]
        for row in scenarios
        if row["expectedErrorCode"] != "SPEECH_FIXTURE_NOT_FOUND"
    } - asr_ids
    if missing_manifest:
        raise AssertionError(f"missing ASR manifest entries: {sorted(missing_manifest)}")

    text_hashes = set()
    for row in tts_rows:
        if row.get("synthetic") is not True or not row.get("generation") or not row.get("license"):
            raise AssertionError("TTS provenance is incomplete")
        expected_text_hash = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        if row["textSha256"] != expected_text_hash or expected_text_hash in text_hashes:
            raise AssertionError("TTS text hash mismatch or duplicate")
        text_hashes.add(expected_text_hash)
        path = safe_path(row["audioPath"])
        if digest(path) != row["sha256"]:
            raise AssertionError("TTS audio hash mismatch")
        validator.validate(
            AudioInput(
                payload=path.read_bytes(),
                content_type="audio/wav",
                encoding=AudioEncoding.WAV_PCM_S16LE,
                sample_rate_hz=row["sampleRateHz"],
                channels=1,
                sample_width_bytes=2,
                synthetic=True,
            )
        )
    return {
        "scenarios": len(scenarios),
        "localeCounts": dict(sorted(locale_counts.items())),
        "asrFixtures": len(asr_rows),
        "ttsFixtures": len(tts_rows),
        "totalAudioBytes": sum(path.stat().st_size for path in path_by_fixture.values())
            + sum(safe_path(row["audioPath"]).stat().st_size for row in tts_rows),
        "hashMismatchCases": sum(
            row["expectedErrorCode"] == "SPEECH_FIXTURE_HASH_MISMATCH" for row in scenarios
        ),
        "malformedCases": sum(row["expectedErrorCode"] in VALIDATION_ERRORS for row in scenarios),
    }


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
