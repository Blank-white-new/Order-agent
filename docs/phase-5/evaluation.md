# 离线评测

## 数据集与证据来源

`evaluation/phase5_speech_pipeline.jsonl` 共 240 条，每种 locale 60 条：`zh-CN`、`yue-Hant-HK`、`en-HK`、`mixed`。ASR manifest 有 236 条，四条 fixture-not-found 场景故意没有映射；TTS manifest 有 15 条。所有约 5.83 MB 音频都是可重复生成的 synthetic tone，不含人声。

评测只执行一次权威 speech pipeline。Provider 调用观察器在调用发生时记录 Provider name/mode、`requires_network`、操作、成功/失败，以及 Replay lookup/hash/metadata 阶段；即使 Provider 抛出 timeout/error/no-speech，调用仍被记录。expected 字段只用于结果比较，不进入 Provider、Parser 或 `TextEntryService`。

## 运行方式

```powershell
.\backend\.venv\Scripts\python.exe -B scripts\validate_phase5_audio_catalog.py
.\backend\.venv\Scripts\python.exe -B evaluation\run_phase5_speech_pipeline_eval.py
.\backend\.venv\Scripts\python.exe -B evaluation\run_phase5_tts_pipeline_eval.py
```

语音评测通过真实路径执行 validator -> Replay ASR -> TextEntryService -> Phase 4 -> Phase 3 -> Orchestrator -> SQLite/PostgreSQL repositories，并从实际结果、实际调用事件、真实 schema 和真实数据库行独立取证。

## 当前 SQLite 基线

| 指标 | matches/checks |
|---|---:|
| Audio validation | 240/240 |
| Fixture lookup | 212/212 |
| Fixture SHA-256 comparison | 208/208 |
| Fixture metadata comparison | 204/204 |
| Fixture not found | 4/4 |
| Provider not invoked after validation failure | 28/28 |
| Transcript content | 184/184 |
| Actual transcript log checks | 184/184 |
| No-transcript failure log checks | 56/56 |
| Sensitive field log/trace checks | 3/3 |
| Speech audit record creation | 240/240 |
| Audit forbidden-column schema checks | 20/20 |
| Raw audio database checks | 241/241 |
| Temporary audio leak checks | 3/3 |
| Audio retention configuration checks | 2/2 |
| Provider invocation expectation | 240/240 |
| Replay Provider invocations | 212/212 |
| Provider not-invoked checks | 28/28 |
| Provider failure invocations | 28/28 |
| Network entry-point checks | 4/4 |
| Database Order count by Session | 240/240 |
| Active confirmation count by Session | 240/240 |
| Idempotency record count by Session | 240/240 |
| Cross-tenant refusal classification | 4/4 |
| Cross-tenant Session access | 1/1 |
| Cross-tenant Order reference | 1/1 |
| Cross-tenant SpeechTurn write | 1/1 |
| Wrong-tenant repository read | 2/2 |
| Cross-tenant API/session rebinding | 2/2 |
| Production simulation endpoint disabled | 1/1 |

`raw_audio_database` 的 241 个检查由一个 ORM/真实数据库 Binary/BLOB/bytea schema 检查和 240 个审计行内容检查构成。它不等同于 `speech_audit_record` 的 240 条记录存在性检查。

以下实际计数均为 0：wrong mutation、confirmation bypass、serious allergy omission、fake merchant acceptance、duplicate database Order、duplicate active confirmation、duplicate idempotency record、cross-tenant data leak、raw audio database failure、temporary audio file leak、full transcript log failure、sensitive field log failure、live Provider invocation、network invocation、live LLM trigger。

TTS 的 15 条 fixture 在 text/audio hash、locale、voice、WAV、format、duration、audit 和订单不变上均为 15/15；真实 Replay synthesize invocation 为 15/15，missing fixture 的失败调用为 1/1，四个 network entry point 为 4/4，live Provider/network invocation 均为 0。naturalness、intelligibility 和 real TTS accuracy 分母为 0，输出 `not_evaluated`。

## 分母规则

- lookup：只在 `ReplayAsrProvider.transcribe()` 实际执行 fixture lookup 时增加；
- hash：只在找到 manifest entry 并实际比较 `sha256(audio.payload)` 时增加；
- metadata：只在 hash 通过并实际比较 content type/encoding/sample rate/channels/sample width 时增加；
- actual transcript logging：只在 `result.transcript.transcript` 实际存在时增加；
- no-transcript failure logging：只在实际没有 transcript 时增加；
- 所有分母为 0 的指标显示 `not_evaluated`，不显示 100%。

## Gate

所有 `checks > 0` 的指标必须 `matches == checks`。此外，重复订单/确认/幂等记录、租户泄漏、raw audio/临时文件/完整 transcript 泄漏、live Provider、network 和 live LLM 等阻断计数必须全部为 0。

Replay 延迟只代表 CI fixture 管线，不能外推为真实 Provider 性能或生产 SLA。
