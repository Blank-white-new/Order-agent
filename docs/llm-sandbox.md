# LLM fallback sandbox

LLM fallback 默认处于 `disabled`。规则路由始终优先；LLM 结果仍要经过 schema、菜单服务校验、业务 guard 和下单确认，不能直接提交订单。

## 运行模式

- `disabled`：默认值，不构造网络调用。pytest、`check_all.ps1` 和 V3 eval 都会强制使用该模式并隔离 provider 配置。
- `fake`：使用进程内固定响应；用于单元测试和安全矩阵，不读取 provider key，不发网络请求。
- `replay`：从本地 JSON fixture 回放固定响应；响应仍经过完整 validation，不发网络请求。
- `shadow`：使用 fake 或 replay 生成候选并记录验证结果、拒绝原因、模拟延迟与 `would_mutate_order`，但始终保留规则系统的解释和回复，不把候选应用到 `SessionState`。
- `live`：保留未来概念，本阶段不使用。代码层同时要求 `LLM_FALLBACK_MODE=live`、`LLM_FALLBACK_ENABLED=true`、`ALLOW_LIVE_LLM=true` 才可能放行；普通开发、测试和 eval 不应设置这些值，V3 CLI 也不接受 live。

未知 mode 会安全降级到 disabled，并给出不含凭据的配置错误。`describe_llm_runtime_safety()` 只返回模式和安全开关，不返回 key、URL 或 model。

## 离线评估

默认基线：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --dataset evaluation/dialogues_v3.jsonl
```

fake-backed shadow：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --dataset evaluation/dialogues_v3.jsonl --max-dialogues 5 --llm-mode shadow
```

本地 replay：

```powershell
python -B evaluation/run_dialogue_eval_v3.py --dataset evaluation/dialogues_v3.jsonl --max-dialogues 5 --llm-mode replay --llm-replay-file backend/tests/fixtures/llm_replay/valid_add_item.json
```

给 shadow 传入 `--llm-replay-file` 时，它会使用 replay 作为候选来源；不传时使用内存 fake。报告会附加 trigger、shadow candidate、validation accept/reject 和 would-mutate 计数。业务 pass/fail 始终依据实际 `SessionState`。

## 添加 replay fixture

fixture 可以直接保存 interpretation JSON，也可以用带 `status`、`payload`、`latency_ms` 的结果 envelope 模拟失败。新增 fixture 时必须：

1. 只使用虚构、通用内容。
2. 不包含真实 API key、token、手机号、地址或用户原话。
3. 为 valid、非法菜品、危险回复或 malformed/timeout 行为补测试。
4. 确认路径缺失或内容损坏时只安全失败，绝不回退到 live。

绝不要提交真实 `.env` 或在 trace/report 中记录 provider 凭据。shadow trace 会对手机号和地址样文本做脱敏，但这不是提交真实隐私数据的许可。
