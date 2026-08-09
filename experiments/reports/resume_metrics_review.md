# Resume Metrics Review

## Experimental baseline

- Experiment base SHA: `e5aea50d3f9e01940420c50260a0ffeb0f651fc5` (Phase 5 HEAD; Phase 5 was required for Replay and was not merged or rewritten).
- Experiment branch: `experiment/performance-and-interruption-benchmarks`.
- Machine: Windows-11-10.0.22621-SP0; Intel64 Family 6 Model 183 Stepping 1, GenuineIntel; 20 logical CPUs; 15.63 GiB RAM.
- Python: 3.13.2 (tags/v3.13.2:4f8bb39, Feb  4 2025, 15:23:48) [MSC v.1942 64 bit (AMD64)].
- Provider configuration: live LLM disabled; token and local latency use no ASR/TTS; speech latency uses Replay ASR/TTS fixture providers only.
- Production regression: final `check_all.ps1 -Build` passed (1281 backend tests, 88 frontend tests, TypeScript and build); explicit Phase 4, Phase 5, and dialogue v3 evaluations passed.
- Audit note: the first full check had one nondeterministic SQLite concurrency failure; the exact failure is retained in `experiments/results/regression_summary.json`, passed 3/3 isolated retries, and the complete rerun passed.

## Qualification table

| Metric | Value | Evidence | Qualifier | Status |
|---|---|---|---|---|
| Projected LLM input-token transfer reduction | 100.00% (95% bootstrap CI 100.00%–100.00%) across 160 conversations / 868 turns | experiments/results/token_cost/analysis.json; three run_*_raw.csv files | offline synthetic conversations; full-context always-LLM baseline; unicode-codepoint-v1 estimator; projected input only; not billed tokens | **VERIFIED_FOR_CV** |
| Projected LLM-call requirement reduction | 100.00%; mean 5.425 → 0.000 calls/conversation | experiments/results/token_cost/analysis.json | offline deterministic configuration with live LLM disabled versus one baseline call per turn | **VERIFIED_FOR_CV** |
| Local text decision latency | p50 32.395 ms; p95 38.281 ms; N=1228 case-level medians across 3 runs | experiments/results/latency/latency_analysis.json; text_run_*_raw.csv | local SQLite benchmark; p50 run drift 3.04%, p95 drift 34.74% (>5%) | **PRELIMINARY_CV_WITH_QUALIFIER** |
| Synthetic Replay input pipeline latency | p50 25.061 ms; p95 45.763 ms; N=240 | experiments/results/latency/latency_analysis.json; replay_run_*_raw.csv | Synthetic Replay fixture lookup, text decision, and audit; optional Replay TTS excluded; not real ASR/TTS/phone latency | **PRELIMINARY_CV_WITH_QUALIFIER** |
| Synthetic interruption classifier | F1 0.838; precision 0.726; recall 0.992; FPR 37.50%; N=240 | experiments/results/barge_in/classifier_analysis.json; selected_test_predictions.csv | programmatic overlapping signals; no intelligible speech or ASR; FPR failed preregistered ≤15% threshold | **NOT_FOR_CV** |
| Synthetic dialogue-state recovery | 100/100 (100.00%), 25 each TP/FP/FN/TN | experiments/results/barge_in/recovery_analysis.json; recovery_raw.csv | synthetic state-machine test; classifier advisory only; not playback interruption or production barge-in | **PRELIMINARY_CV_WITH_QUALIFIER** |
| 360 multilingual text scenarios | 360/360 intent and classification matches in both auto and assisted modes; 0 wrong mutations / confirmation bypasses | evaluation/phase4_multilingual_text.jsonl; explicit Phase 4 regression on 2026-08-04 | synthetic/offline multilingual evaluation | **VERIFIED_FOR_CV** |
| 240 synthetic Replay speech-pipeline scenarios | 240 scenarios; 0 wrong mutations, confirmation bypasses, live-provider invocations, or live-LLM triggers | evaluation/phase5_speech_pipeline.jsonl; explicit Phase 5 regression on 2026-08-04 | synthetic Replay Provider; not ASR/TTS accuracy or real speech | **VERIFIED_FOR_CV** |
| Actual API cost / production bill | NOT_EVALUATED | No verified price source and no live provider call | projected input estimates only | **NOT_FOR_CV** |
| Real phone / speech / ASR / TTS latency or accuracy | NOT_EVALUATED | provider metadata: no live ASR/TTS, PSTN, SIP, WebRTC, call, or customer | none available | **NOT_FOR_CV** |
| Real-world barge-in accuracy / success | NOT_IMPLEMENTED / NOT_EVALUATED | prototype is isolated under experiments/barge_in | synthetic state-machine and signal experiments only | **NOT_FOR_CV** |
| Restaurant success, complaint, refund, or business cost rate | NOT_EVALUATED | No real restaurant or customer data used | none available | **NOT_FOR_CV** |

## VERIFIED_FOR_CV

The only **new** CV claim authorized this round is the paired Token/model-call result. Existing verified 360-text-scenario and 240-Replay-scenario claims remain. The CV wording must say **projected**, **offline/synthetic**, and must not imply billed tokens or an actual API bill.

Authorized English wording:

> Against a documented full-context LLM baseline, reduced projected LLM input-token usage and model-call requirements by 100% across 160 synthetic ordering conversations (868 turns; offline deterministic configuration; 95% bootstrap CI 100–100%).

Authorized Chinese wording:

> 相较有文档定义的完整上下文 LLM 基线，在 160 组合成订餐会话（868 轮）的离线确定性配置中，预估 LLM 输入 Token 传输量与模型调用需求均降低 100%（Bootstrap 95% CI：100%–100%）。

## PRELIMINARY_CV_WITH_QUALIFIER

- Local p50/p95 values remain preliminary because p95 drift across runs was 34.74%.
- Synthetic Replay latency is reproducible but is not real speech latency.
- Recovery was 100/100 only in a synthetic dialogue-state suite. Because the upstream detector failed its FPR gate, it is not promoted in this CV update.

## NOT_FOR_CV

- Synthetic interruption detector: F1 0.838, but FPR 37.50% exceeded the preregistered limit.
- Real phone/speech latency, real ASR/TTS accuracy, real barge-in, production success/complaint rate, actual restaurant cost, and actual API billing were not evaluated.

## Leakage and baseline audit

- Baseline and current receive identical user conversations; raw turn identities match across three runs.
- Expected Phase 4 intent/classification values are discarded when the Token dataset is constructed and are never passed to runtime.
- Replay receives only fixture audio/metadata/ID; `expectedTranscript` is never passed to the provider.
- Barge-in model features exclude label, semantic text, locale, category, template ID, SNR, onset, and waveform seed.
- The rejected category-unbalanced pilot split is retained rather than deleted; its test set was not opened.
- No experiment path changes `AUTO_DRAFT`, `CONFIRM`, `HANDOFF`, or `REFUSE`; no experiment is imported by production.

## CV update decision

- Replace only the qualitative efficiency bullet with the authorized paired Token/model-call claim.
- Keep the five-bullet project structure.
- Retain the existing 360 multilingual text and 240 synthetic Replay facts.
- Do not add local latency, synthetic detector F1, recovery, real-speech, or cost claims this round.
