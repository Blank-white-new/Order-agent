# V3 对话评估

V3 是一个可版本化的离线对话回归基线。它通过现有 `TextEntryService` 顺序执行每段对话，记录响应、语义路由 trace 和 `SessionState` 前后变化，但不修改应用业务逻辑。

## 默认离线保证

runner 在导入应用模块之前执行三层护栏：

1. 强制设置 `LLM_FALLBACK_MODE=disabled`、`LLM_FALLBACK_ENABLED=false`、`ALLOW_LIVE_LLM=false` 和 `LLM_FALLBACK_SPECULATIVE_ENABLED=false`。
2. 从当前进程清除 LLM provider 的 key、base URL、model 和 provider 配置，并把 `BACKEND_ENV_FILE` 指向不存在的临时路径，因此不会读取项目 `.env`。
3. 用 `OfflineOnlyLLMClient` 替换 Orchestrator 的 client；即使配置意外回流，网络解释调用也会直接报错并被记录为样本失败。

runner 只开放 disabled/fake/replay/shadow，没有 live 参数，也不会调用 ASR/TTS。fake/replay/shadow 都是本地来源。不要把真实凭据写进命令、数据集或 JSON 报告。

## 运行

在仓库根目录执行：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --dataset evaluation/dialogues_v3.jsonl
```

只运行前 5 条：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --dataset evaluation/dialogues_v3.jsonl --max-dialogues 5
```

运行本地 shadow 或 replay：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --max-dialogues 5 --llm-mode shadow
python -B evaluation/run_dialogue_eval_v3.py --max-dialogues 5 --llm-mode replay --llm-replay-file backend/tests/fixtures/llm_replay/valid_add_item.json
```

shadow 不应用候选，业务 pass/fail 仍依据真实规则状态；报告附加 LLM trigger、candidate、validation accept/reject 和 would-mutate 计数。

按分类或预期结果筛选：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --category normal_order
python -B evaluation/run_dialogue_eval_v3.py --expected-result-type should_clarify
```

输出详细逐样本状态或保存机器可读报告：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --verbose --json-report artifacts/eval-v3.json
```

默认情况下，业务语义未达到预期的样本会显示为 failed，但进程退出码仍为 0，便于第一版建立基线。需要把失败作为门禁时显式添加：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --fail-on-regression
```

JSONL schema、分类和断言字段详见 [schema_v3.md](schema_v3.md)。

## 解释结果

console summary 包含总数、passed、failed、pass rate、按 category 与 `expected_result_type` 的分组统计，以及：

- `false mutation count`：`allow_order_mutation=false` 的计分轮中发生订单变化的次数。
- `confirmation bypass count`：非 `confirm` 意图把订单从未提交变为已提交的次数。
- `fallback count`：计分轮进入 fallback 的次数。

每个失败样本会打印 ID、分类、结果类型、计分轮输入、预期、实际、状态 diff 摘要和失败原因。第一版允许语义样本失败；这些失败是后续业务优化的定位清单，不应在本阶段通过修改语义规则来“刷绿”。

## 后续接入 CI

建议先保存一份经过评审的基线，再在 CI 中运行数据 schema 测试和小规模 smoke eval。指标稳定后，可对关键分类使用 `--fail-on-regression`，或比较 `--json-report` 的 false mutation、confirmation bypass 与 pass rate。CI 必须继续使用离线环境，且不得注入 live provider 凭据。
