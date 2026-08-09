# Token efficiency v2

This experiment replaces the v1 disabled-LLM comparison with a paired,
task-equivalent resource simulation:

- **Baseline A** invokes a fixed target-model interface on every turn with a
  compact system instruction, branch context, only relevant service-layer menu
  and policy context, full dialogue history, and the current input.
- **System B** runs the unchanged rules-first production path and records a
  simulated invocation only when the real ambiguity/fallback signals satisfy
  the frozen selective-LLM policy.
- Both use the same target model definition, tokenizer implementation,
  invocation accounting, deterministic decision replay, validation layer, and
  160-conversation dataset.

The replay provider controls semantic quality without a network call. It does
not measure live-model accuracy. Expected Phase 4 fields are evaluator-only and
are never accepted by prompt builders, invocation policy, or production runtime.
Output tokens are not measured or invented.

## Run order

```powershell
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.audit_dataset
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.build_quality_reference
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.run_benchmark --run-id 1
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.run_benchmark --run-id 2
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.run_benchmark --run-id 3
.\backend\.venv\Scripts\python.exe -m experiments.token_efficiency_v2.analyze
```

Install the isolated analysis dependency with:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r experiments\requirements.txt
```

No command enables live LLM, ASR, TTS, telephony, or a provider credential.
