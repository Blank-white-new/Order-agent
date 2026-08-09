# Reproducible offline experiments

This directory is isolated from production behavior. It never enables a live
LLM, real ASR, real TTS, telephone transport, customer data, or model download.
The experiment base is
`e5aea50d3f9e01940420c50260a0ffeb0f651fc5` (Phase 5 final HEAD at branch
creation). Generated datasets remain under `experiments/datasets`; raw rows,
metadata, and derived summaries remain under `experiments/results`; reports and
figures remain under `experiments/reports`.

`protocol.json` was written before the first benchmark run. It fixes seeds,
bootstrap count, stability rules, terminology, and CV gates so those rules are
not selected after seeing results.

## Runtime boundary

- Token benchmark v2: the fair paired comparison is under
  `token_efficiency_v2`. Both architectures use the fixed
  `gpt-4o-mini-2024-07-18` target definition and `tiktoken==0.13.0`
  (`o200k_base`). Baseline A invokes a compact full-context interface every
  turn; System B invokes the same offline decision-replay interface only under
  the frozen selective-LLM policy. Counts are model-specific input-token
  estimates, never billed tokens, and output tokens/cost are not evaluated.
- Token benchmark v1 under `token_cost` is retained for auditability. Its
  `unicode-codepoint-v1` / disabled-live-LLM 100% result is superseded and is
  explicitly not eligible for CV use.
- Text latency: current `TextEntryService` path with SQLite, excluding process
  startup, imports, dataset loading, migrations, and seed work.
- Speech latency: Phase 5 Replay fixtures and providers only. It is not real
  speech, real ASR/TTS, telephone latency, or a production SLA.
- Barge-in: an isolated acoustic/temporal prototype over locally generated
  overlapping tone/noise waveforms. Generator text and labels are provenance
  only and are not classifier features. It is not wired into production.

## Reproduction

Use the repository Python for backend-path experiments and a Python containing
the two pinned optional analysis dependencies for waveform analysis and PNGs.
Every runner supports explicit run IDs and writes JSON metadata plus raw CSV.
Reports are always recomputed from raw files; do not hand-edit result tables.

From the repository root in PowerShell:

```powershell
# Fair selective-LLM token benchmark v2 (no provider/network call)
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.audit_dataset
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.build_quality_reference
1..3 | ForEach-Object {
  .\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.run_benchmark --run-id $_
}
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.analyze

# Token / projected input transfer (no provider call)
.\backend\.venv\Scripts\python.exe -m experiments.token_cost.build_dataset
1..3 | ForEach-Object {
  .\backend\.venv\Scripts\python.exe -m experiments.token_cost.run --run-id $_
}
python -m experiments.token_cost.analyze

# Local decision and Synthetic Replay latency (run sequentially)
1..3 | ForEach-Object {
  .\backend\.venv\Scripts\python.exe -m experiments.latency.run_text_latency --run-id $_
  .\backend\.venv\Scripts\python.exe -m experiments.latency.run_replay_speech_latency --run-id $_
}
python -m experiments.latency.analyze

# Synthetic programmatic interruption prototype
python -m experiments.barge_in.generate_dataset
python -m experiments.barge_in.features
python -m experiments.barge_in.train
python -m experiments.barge_in.evaluate
.\backend\.venv\Scripts\python.exe -m experiments.barge_in.recovery_eval
python -m experiments.barge_in.analyze

# Eligibility audit after regressions
.\backend\.venv\Scripts\python.exe -m experiments.audit
```

Here `python` denotes an offline environment satisfying
`experiments/requirements.txt`; the experiment contains its own Logistic
Regression and Gradient Boosting implementations and does not download a model.
The checked-in raw rows and metadata allow every report table to be recomputed
without repeating host-sensitive timing unless a fresh machine run is desired.

## Tests and production regressions

```powershell
.\backend\.venv\Scripts\python.exe -m pytest experiments\tests\test_token_efficiency_v2.py -q
.\backend\.venv\Scripts\python.exe -m pytest experiments\tests\test_token_and_latency.py -q
python -m experiments.tests.run_barge_tests
.\scripts\check_all.ps1 -Build
.\backend\.venv\Scripts\python.exe evaluation\run_phase4_multilingual_text_eval.py --mode both
.\backend\.venv\Scripts\python.exe evaluation\run_phase5_speech_pipeline_eval.py
.\backend\.venv\Scripts\python.exe evaluation\run_dialogue_eval_v3.py `
  --dataset evaluation\dialogues_v3.jsonl `
  --fail-on-regression
```

The first full regression attempt in this run exposed one nondeterministic
SQLite concurrency-test failure. It passed three isolated retries and the full
rerun passed; both facts are retained in `results/regression_summary.json`.
