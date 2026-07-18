# Phase 5 验收矩阵

| 要求 | 实现证据 | 自动验证 |
|---|---|---|
| 音频契约与严格校验 | `contracts.py`、`audio_validator.py` | validator tests、catalog validator、240/240 validation |
| Provider interface/Registry | `provider.py`、`provider_registry.py` | Replay Provider tests |
| 真实 Provider 调用统计 | `invocation_observer.py` | invocation expectation 240/240、Replay 212/212、failure 28/28 |
| Replay lookup/hash/metadata 分层 | `replay_asr_provider.py` | lookup 212/212、hash 208/208、metadata 204/204、missing 4/4 |
| validation 失败不调用 Provider | validator before registry | not-invoked 28/28 |
| production 默认关闭/fail closed | `config.py`、API guard | configuration 2/2、production endpoint 1/1 |
| 唯一 TextEntryService 路径 | `speech_pipeline_service.py` | pipeline、安全集成与 240 场景 eval |
| 确认前不落单 | 原 Orchestrator/订单规则不变 | mutation 240/240、DB Order/confirmation/idempotency 各 240/240 |
| no-speech/low-confidence/failure 不误修改 | confidence mapping + stable failures | 4/4、4/4、16/16 |
| TTS 不改变订单 | output-only synthesis | TTS order unchanged 15/15 |
| 审计记录与 raw audio 分开 | audit allow-list + schema/content checks | audit 240/240、schema 20/20、raw DB 241/241 |
| transcript 和敏感字段不记录 | per-scenario actual result log scan | actual transcript 184/184、no-transcript 56/56、sensitive 3/3 |
| 临时音频不残留 | scoped temp/repository snapshots | 3/3、API upload snapshot test |
| 租户文本分类 | Phase 3 refusal | refusal classification 4/4 |
| 租户 Session/API 隔离 | bound Session + stable API error | Session 1/1、API rebinding 2/2 |
| 租户 DB/Repository 隔离 | composite FK + scoped repository | SpeechTurn 1/1、Order ref 1/1、repository 2/2 |
| 无网络/live Provider/live LLM | patched network entry points + invocation events | network 4/4、live/network/LLM counts 0 |
| SQLite/PostgreSQL | UOW/migration/repositories | 本地 SQLite + PostgreSQL CI |
| 全量回归 | `scripts/check_all.ps1` | Windows CI + PostgreSQL CI |

## 阻断条件

以下任一非零即失败：wrong mutation、confirmation bypass、serious allergy omission、fake merchant acceptance、duplicate database Order、duplicate active confirmation、duplicate idempotency record、cross-tenant data leak、raw audio database failure、temporary audio file leak、full transcript log failure、sensitive field log failure、live Provider invocation、network invocation、live LLM trigger。

所有 `checks > 0` 的指标必须 `matches == checks`；分母为 0 时必须输出 `not_evaluated`。

## 明确非目标

真实电话、PSTN/SIP/RTP/WebRTC、真实 ASR/TTS Provider、真实顾客录音、streaming、barge-in、G.711、真实人工坐席、POS、支付、商家接受、生产凭证、真实语音准确率、TTS 可懂度和自然度均未实现。
