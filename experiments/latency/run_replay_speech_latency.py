from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter_ns

from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file, sha256_paths
from experiments.common.offline import force_offline_environment


force_offline_environment("replay-speech-latency")
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.speech.contracts import AudioInput  # noqa: E402
from app.speech.errors import SpeechError  # noqa: E402
from app.speech.formats import AudioEncoding, SpeechOutcome  # noqa: E402
from evaluation.phase5_harness import make_phase5_context  # noqa: E402


DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"
ASR_MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_asr_manifest.jsonl"
TTS_MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "latency"


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    def reset(self) -> None:
        self.events.clear()

    def record(self, name: str, elapsed_ns: int) -> None:
        self.events.append((name, elapsed_ns))

    def total(self, name: str) -> int:
        return sum(elapsed for event, elapsed in self.events if event == name)

    def count(self, name: str) -> int:
        return sum(event == name for event, _ in self.events)


class TimedValidator:
    def __init__(self, inner, recorder: Recorder) -> None:
        self.inner = inner
        self.recorder = recorder

    def validate(self, audio):
        started = perf_counter_ns()
        try:
            return self.inner.validate(audio)
        finally:
            self.recorder.record("audio_validation", perf_counter_ns() - started)


class TimedAsrProvider:
    def __init__(self, inner, recorder: Recorder) -> None:
        self.inner = inner
        self.recorder = recorder

    @property
    def name(self):
        return self.inner.name

    def capabilities(self):
        return self.inner.capabilities()

    def transcribe(self, request):
        started = perf_counter_ns()
        try:
            return self.inner.transcribe(request)
        finally:
            self.recorder.record("replay_asr", perf_counter_ns() - started)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class TimedTtsProvider:
    def __init__(self, inner, recorder: Recorder) -> None:
        self.inner = inner
        self.recorder = recorder

    @property
    def name(self):
        return self.inner.name

    def capabilities(self):
        return self.inner.capabilities()

    def synthesize(self, request):
        started = perf_counter_ns()
        try:
            return self.inner.synthesize(request)
        finally:
            self.recorder.record("replay_tts_provider", perf_counter_ns() - started)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class TimedTextEntry:
    def __init__(self, inner, recorder: Recorder) -> None:
        self.inner = inner
        self.recorder = recorder

    async def handle_text_message(self, *args, **kwargs):
        started = perf_counter_ns()
        try:
            return await self.inner.handle_text_message(*args, **kwargs)
        finally:
            self.recorder.record("text_decision", perf_counter_ns() - started)

    async def handle_non_text_input_failure(self, *args, **kwargs):
        started = perf_counter_ns()
        try:
            return await self.inner.handle_non_text_input_failure(*args, **kwargs)
        finally:
            self.recorder.record("text_decision", perf_counter_ns() - started)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def audio_input(row: dict, payload: bytes) -> AudioInput:
    return AudioInput(
        payload=payload,
        content_type=row["contentType"],
        encoding=AudioEncoding(row["encoding"]),
        sample_rate_hz=row["sampleRateHz"],
        channels=row["channels"],
        sample_width_bytes=row["sampleWidthBytes"],
        fixture_id=row["fixtureId"],
        synthetic=True,
    )


def instrument(context, recorder: Recorder) -> None:
    validator = TimedValidator(context.pipeline.validator, recorder)
    context.pipeline.validator = validator
    context.pipeline.normalizer.validator = validator
    context.registry._asr["replay"] = TimedAsrProvider(context.registry._asr["replay"], recorder)
    context.registry._tts["replay"] = TimedTtsProvider(context.registry._tts["replay"], recorder)
    context.pipeline.text_entry_service = TimedTextEntry(context.text_entry, recorder)


async def run_benchmark(*, run_id: int, results_dir: Path, warmup_count: int = 20) -> dict:
    force_offline_environment("replay-speech-latency")
    rows = read_jsonl(DATASET)
    loaded = [(row, (ROOT / row["audioPath"]).read_bytes()) for row in rows]
    tts_rows = read_jsonl(TTS_MANIFEST)
    results_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"order-replay-latency-{run_id}-") as temp_dir:
        context = make_phase5_context(f"sqlite:///{Path(temp_dir, 'replay.db').as_posix()}")
        recorder = Recorder()
        instrument(context, recorder)
        raw: list[dict] = []
        try:
            successful_warmups = [item for item in loaded if item[0]["expectedSpeechOutcome"] in {"SUCCESS", "LOW_CONFIDENCE"}]
            for index in range(warmup_count):
                row, payload = successful_warmups[index % len(successful_warmups)]
                recorder.reset()
                await context.pipeline.handle_audio_message(
                    session_id=f"replay-warmup-r{run_id}-{index}",
                    restaurant_code=row["restaurantCode"],
                    branch_code=row["branchCode"],
                    audio=audio_input(row, payload),
                    idempotency_key=f"replay-warmup-r{run_id}-{index}",
                )

            for index, (row, payload) in enumerate(loaded, start=1):
                session_id = f"replay-r{run_id}-{row['scenarioId']}"
                for setup_index, setup in enumerate(row.get("setupInputs") or []):
                    await context.text_entry.handle_text_message(
                        session_id,
                        setup,
                        restaurant_code=row["restaurantCode"],
                        branch_code=row["branchCode"],
                        idempotency_key=f"replay-setup-r{run_id}-{index}-{setup_index}",
                    )
                recorder.reset()
                error_code = ""
                outcome = ""
                result = None
                started = perf_counter_ns()
                try:
                    result = await context.pipeline.handle_audio_message(
                        session_id=session_id,
                        restaurant_code=row["restaurantCode"],
                        branch_code=row["branchCode"],
                        audio=audio_input(row, payload),
                        idempotency_key=f"replay-measured-r{run_id}-{index}",
                        synthesize_response=False,
                    )
                    outcome = result.outcome.value
                    error_code = result.error_code or ""
                except SpeechError as exc:
                    outcome = SpeechOutcome.VALIDATION_ERROR.value
                    error_code = exc.code
                end_to_end_ns = perf_counter_ns() - started
                state = (result.text_result or {}).get("state", {}) if result else {}
                trace = (result.text_result or {}).get("trace", {}) if result else {}
                decision = (trace.get("safety") or {}).get("classification") or state.get("safety_classification") or ""
                raw.append(
                    {
                        "run_id": run_id,
                        "record_type": "audio_pipeline",
                        "scenario_id": row["scenarioId"],
                        "semantic_category": row["semanticCategory"],
                        "locale": row["locale"],
                        "decision_class": decision,
                        "outcome": outcome,
                        "error_code": error_code,
                        "audio_validation_calls": recorder.count("audio_validation"),
                        "audio_validation_ns": recorder.total("audio_validation"),
                        "audio_validation_ms": recorder.total("audio_validation") / 1_000_000,
                        "replay_asr_calls": recorder.count("replay_asr"),
                        "replay_asr_ns": recorder.total("replay_asr"),
                        "replay_asr_ms": recorder.total("replay_asr") / 1_000_000,
                        "text_decision_calls": recorder.count("text_decision"),
                        "text_decision_ns": recorder.total("text_decision"),
                        "text_decision_ms": recorder.total("text_decision") / 1_000_000,
                        "replay_tts_calls": 0,
                        "replay_tts_ns": "",
                        "replay_tts_ms": "",
                        "end_to_end_ns": end_to_end_ns,
                        "end_to_end_ms": end_to_end_ns / 1_000_000,
                        "synthesize_response": False,
                        "timer": "time.perf_counter_ns",
                    }
                )

            # Replay TTS is an optional output stage. It is measured separately
            # with every reviewed manifest entry repeated seven times (105 calls).
            for index in range(warmup_count):
                row = tts_rows[index % len(tts_rows)]
                context.pipeline.synthesize(text=row["text"], locale=row["locale"])
            for repetition in range(7):
                for row in tts_rows:
                    recorder.reset()
                    started = perf_counter_ns()
                    context.pipeline.synthesize(text=row["text"], locale=row["locale"])
                    elapsed_ns = perf_counter_ns() - started
                    raw.append(
                        {
                            "run_id": run_id,
                            "record_type": "replay_tts",
                            "scenario_id": f"tts-{row['messageKey']}-r{repetition + 1}",
                            "semantic_category": "tts_output",
                            "locale": row["locale"],
                            "decision_class": "NOT_APPLICABLE",
                            "outcome": "SUCCESS",
                            "error_code": "",
                            "audio_validation_calls": recorder.count("audio_validation"),
                            "audio_validation_ns": recorder.total("audio_validation"),
                            "audio_validation_ms": recorder.total("audio_validation") / 1_000_000,
                            "replay_asr_calls": 0,
                            "replay_asr_ns": "",
                            "replay_asr_ms": "",
                            "text_decision_calls": 0,
                            "text_decision_ns": "",
                            "text_decision_ms": "",
                            "replay_tts_calls": recorder.count("replay_tts_provider"),
                            "replay_tts_ns": elapsed_ns,
                            "replay_tts_ms": elapsed_ns / 1_000_000,
                            "end_to_end_ns": "",
                            "end_to_end_ms": "",
                            "synthesize_response": True,
                            "timer": "time.perf_counter_ns",
                        }
                    )
        finally:
            context.database.engine.dispose()

    raw_path = results_dir / f"replay_run_{run_id}_raw.csv"
    write_csv(raw_path, raw)
    audio_paths = tuple(ROOT / row["audioPath"] for row in rows)
    metadata = collect_metadata(
        dataset_sha256=sha256_paths((DATASET, ASR_MANIFEST, TTS_MANIFEST, *audio_paths)),
        random_seed=42,
        warmup_count=warmup_count,
        measurement_count=len(raw),
        provider_mode="synthetic_replay_offline",
        asr_provider="ReplayAsrProvider (fixture lookup; not ASR)",
        tts_provider="ReplayTtsProvider (fixture lookup; not TTS synthesis)",
        extra={
            "run_id": run_id,
            "experiment": "synthetic_replay_pipeline_latency",
            "timer": "time.perf_counter_ns",
            "audio_pipeline_measurements": len(rows),
            "tts_measurements": len(tts_rows) * 7,
            "tts_warmup_count": warmup_count,
            "database": "SQLite (temporary per run)",
            "synthesis_in_audio_end_to_end": False,
            "stage_instrumentation": "experiment-only wrappers; production classes unchanged",
            "excluded": ["Python startup", "imports", "migration", "seeding", "fixture loading", "warmup", "setup inputs", "logging"],
            "raw_csv": str(raw_path.relative_to(ROOT)),
            "raw_csv_sha256": sha256_file(raw_path),
            "expected_transcript_passed_to_provider": False,
            "live_provider_invocations": 0,
        },
    )
    write_json(results_dir / f"replay_run_{run_id}_metadata.json", metadata)
    payload = {"run_id": run_id, "audio_pipeline_measurements": len(rows), "tts_measurements": len(tts_rows) * 7, "raw_csv_sha256": sha256_file(raw_path)}
    write_json(results_dir / f"replay_run_{run_id}_summary.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--warmup-count", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_benchmark(run_id=args.run_id, results_dir=args.results_dir, warmup_count=args.warmup_count)), indent=2))


if __name__ == "__main__":
    main()
