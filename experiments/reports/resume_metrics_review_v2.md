# Resume Metrics Review v2

| Metric | Value | Evidence | Qualifier | Status |
|---|---|---|---|---|
| Selective-LLM estimated input-token reduction | 92.25%; conversation CI [89.87%, 94.39%], template-cluster CI [86.08%, 96.74%] | `analysis.json`, three `run_*_raw.csv`, prompt examples | 160 synthetic conversations; offline prompt-accounting benchmark; deterministic decision replay; model-specific `gpt-4o-mini-2024-07-18` / `o200k_base` tokenizer estimate; prompt/input requirement comparison; not actual billed tokens; not live-model accuracy evidence; not production cost evidence | **CV_ELIGIBLE_WITH_QUALIFIER** |
| Simulated LLM invocation reduction | 94.01%; 5.425 -> 0.325 requirements/conversation | paired conversation table | simulated invocation requirement; not actual API calls; selective policy is experiment-only; not currently wired as live production LLM routing | **CV_ELIGIBLE_WITH_QUALIFIER** |
| Decision-replay equivalence | 160/160 for both architecture accounting paths | frozen reference + independent execution paths | confirms that both accounting paths were evaluated against the same frozen deterministic outcome reference; does not measure target-model semantic accuracy | **EXPERIMENT_VALIDATION_ONLY** |
| Blocking safety violations | 0 observed for both accounting paths | raw quality columns and Phase 4 safety labels | zero observed blocking safety violations in the offline synthetic evaluation set; not a production zero-error claim | **VERIFIED_FOR_CV** |
| V1 disabled-LLM comparison | superseded | `token_cost_benchmark.md` | configuration-defined comparison | **NOT_FOR_CV** |
| Local decision / Synthetic Replay latency | unchanged from prior audit | `latency_benchmark.md` | preliminary local/synthetic; not rerun | **PRELIMINARY_NOT_FOR_CV** |
| Synthetic interruption F1/FPR and recovery | FPR 37.5%; unchanged | `barge_in_benchmark.md` | not rerun; failed CV gate | **NOT_FOR_CV** |
| Actual LLM accuracy | NOT_EVALUATED | no live target-model inference | deterministic replay is not semantic-accuracy evidence | **NOT_EVALUATED** |
| Actual API cost or production bill | NOT_EVALUATED | no provider usage or verified price assumption | estimated prompt/input requirements are not billing or cost evidence | **NOT_EVALUATED** |
| Real phone/speech/ASR/TTS or restaurant outcomes | NOT_EVALUATED | no live data/provider/telephony | none | **NOT_EVALUATED** |

## Gate decision

The resource-accounting checks pass. Because semantic decisions are replayed rather than generated independently by live target-model inference, only the estimated input-token and simulated invocation metrics are **CV_ELIGIBLE_WITH_QUALIFIER**. Decision-replay equivalence is **EXPERIMENT_VALIDATION_ONLY** and cannot support an accuracy or performance-preservation claim.

## Allowed English wording

Built an offline prompt-accounting benchmark over 160 synthetic ordering conversations (868 turns); a rules-first selective-LLM design reduced model-specific estimated input-token requirements by 92.3% and simulated model-invocation requirements by 94.0% versus a compact full-context LLM baseline.

## Allowed Chinese wording

构建覆盖 160 组合成订餐会话（868 轮）的离线 Prompt 资源评测基准；相较紧凑完整上下文 LLM 基线，规则优先的 selective-LLM 实验设计使模型特定 tokenizer 估算的输入 Token 需求降低 92.3%，模拟模型调用需求降低 94.0%。

The superseded disabled-LLM CV claim must be replaced by this v2 result. No latency, interruption, recovery, actual cost, live-model accuracy, performance-preservation, or production claim is authorized.

## Remaining evidence for a live-model performance claim

Upgrading the resource-accounting result to a claim that token requirements fell while model task performance remained equivalent requires a new live-model experiment; it is not part of this benchmark and is not run in this cleanup.

That future experiment must compare Baseline A actual target-LLM inference with System B actual selective-LLM inference using the same model, tokenizer, dataset, and actual semantic outputs. It must evaluate intent accuracy, mutation accuracy, safety, completion, input/output token usage, latency, and cost. Until then, the 92.25% result remains an offline model-specific prompt/input-requirement estimate, and the 94.01% result remains a simulated invocation-requirement estimate.
