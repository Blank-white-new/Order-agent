# Latency Benchmark

## Question

What is the measured local decision latency of the current text system, and what is the component latency of the existing fully offline Synthetic Replay speech fixture pipeline?

## Hypothesis

The deterministic local path should complete on a local machine without network or live-model delay. Replay timings should remain explicitly separate from real speech latency.

## Dataset

- Local text: 1,228 cases per run (360 Phase 4 scenarios plus 868 turns from 160 complete conversations), three sequential runs, 20 excluded warm-ups per run.
- Synthetic Replay input: 240 Phase 5 fixtures per run, three sequential runs, 20 excluded warm-ups per run.
- Replay TTS: 15 reviewed tone fixtures × 7 repetitions = 105 timings per run, plus 20 excluded warm-ups.
- The measurement unit in the primary summary is each case's median across the three runs; raw timings for every run remain available.

## Baseline

A real direct-LLM latency baseline is **NOT_EVALUATED**. `ALLOW_LIVE_LLM=false` was not changed. A controlled live-provider benchmark would be required for that comparison.

## Current system

Local text covers `raw text → locale → canonical parser → safety decision → state transition → response object`. It includes local SQLite state work but excludes network, ASR, live LLM, and TTS.

Synthetic Replay covers `audio bytes → AudioValidator/normalizer → Replay ASR fixture lookup → TranscriptEnvelope → TextEntryService → decision`. Replay TTS fixture lookup is measured as a separate optional output stage; it is not included in audio end-to-end input latency.

## Method

- `time.perf_counter_ns()` surrounds only the relevant call.
- Python startup, imports, database migration/seeding, fixture/file loading, setup turns, logging, and warm-up are outside the timed region.
- Stage timing uses experiment-only wrappers; production classes and safety semantics are unchanged.
- Median and p95 intervals use 10,000 bootstrap resamples with seed 42/43 at the case level.
- All results in this report are SQLite measurements; no PostgreSQL result is mixed in.

## Metrics and results — local decision latency

N = 1228 cases. Primary aggregation: case-level median across three runs.

| Metric | Value |
|---|---:|
| Mean | 29.909 ms |
| Median / p50 | 32.395 ms |
| p90 | 36.119 ms |
| p95 | 38.281 ms |
| p99 | 62.151 ms |
| Max | 68.893 ms |
| Standard deviation | 8.065 ms |

- Median: 32.395 ms (95% CI 32.249–32.525).
- p95: 38.281 ms (95% CI 37.532–38.636).
- Decision-path and routine/ambiguity/safety breakdowns, with separate CIs, are in `experiments/results/latency/text_group_summary.csv`.

## Metrics and results — Synthetic Replay Pipeline Latency

| Stage | N | p50 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| audio_validation | 240 | 0.031 ms | 0.040 ms | 0.048 ms | 0.053 ms |
| replay_asr | 240 | 0.034 ms | 0.038 ms | 0.040 ms | 0.045 ms |
| text_decision | 240 | 17.016 ms | 38.496 ms | 44.680 ms | 50.794 ms |
| end_to_end | 240 | 25.061 ms | 45.763 ms | 51.310 ms | 58.974 ms |
| replay_tts | 105 | 0.299 ms | 0.325 ms | 0.355 ms | 0.375 ms |


- Synthetic Replay end-to-end median: 25.061 ms (95% CI 23.185–31.501).
- Synthetic Replay end-to-end p95: 45.763 ms (95% CI 45.133–46.413).
- Stage, decision-path, outcome, and category tables are retained in CSV and JSON.

## Confidence intervals and stability

Local per-run p50 values were 32.071, 32.225, 33.058 ms; per-run p95 values were 38.271, 38.280, 53.311 ms. Relative drift was 3.04% for p50 and 34.74% for p95.

Synthetic Replay end-to-end p50 relative drift was 2.37%; p95 relative drift was 4.08%.

The third local run slowed near its final measurement block, producing p95 drift above the preregistered 5% investigation threshold. That run is retained and included in the case-level aggregation; no fastest run was selected. This instability limits the local latency CV status.

## Error analysis

- All four local decision classes were retained: AUTO_DRAFT, CONFIRM, HANDOFF, and REFUSE.
- Invalid Replay inputs remain in end-to-end timing. Missing stages are blank rather than replaced with zero.
- Replay ASR/TTS times measure deterministic fixture validation and lookup, not recognition or speech synthesis.

## Limitations

- This is one Windows host and temporary SQLite, not a production deployment or capacity test.
- No network, real LLM, real ASR, real TTS, caller audio, telephony, or streaming barge-in is measured.
- End-to-end Replay input timing excludes optional TTS; the TTS stage is shown separately.
- A real direct-LLM latency comparison requires a controlled live-provider benchmark and is not measured in this offline experiment.

## Reproducibility

Run each latency runner with `--run-id 1`, `2`, and `3`, then run `analyze.py`. Raw nanosecond/millisecond CSV, metadata JSON, case-level summaries, bootstrap intervals, hashes, and PNG charts are retained.

## CV eligibility

- Local decision latency: **PRELIMINARY_CV_WITH_QUALIFIER** with the mandatory qualifier “local benchmark.” p95 stability exceeded the 5% investigation threshold, so the p50/p95 pair is not promoted as a fully verified CV claim in this run.
- Synthetic Replay latency: **PRELIMINARY_CV_WITH_QUALIFIER**, only with the qualifier “synthetic Replay benchmark.”
- Real speech/phone latency: **NOT_EVALUATED / NOT_FOR_CV**.
