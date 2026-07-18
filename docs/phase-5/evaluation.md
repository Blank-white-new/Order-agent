# 离线评测

## 数据集

`evaluation/phase5_speech_pipeline.jsonl` 共 240 条，每种 locale 60 条：`zh-CN`、`yue-Hant-HK`、`en-HK`、`mixed`。正常业务场景继承 Phase 4 canonical 多语言覆盖；负面场景包括 no-speech、low confidence、timeout、Provider error/truncated、unsupported language、hash mismatch、malformed/静音/过大/采样率/时长/MIME/channels 和 fixture missing。

ASR manifest 有 236 条（4 条 fixture-not-found 场景故意没有映射），TTS manifest 有 15 条。四种 locale 各有一条 8 kHz raw PCM 成功场景，其余正常输入为 16 kHz WAV；所有约 5.83 MB 音频都是可重复生成的 synthetic tone。

## 运行方式

```powershell
.\backend\.venv\Scripts\python.exe scripts\validate_phase5_audio_catalog.py
.\backend\.venv\Scripts\python.exe evaluation\run_phase5_speech_pipeline_eval.py
.\backend\.venv\Scripts\python.exe evaluation\run_phase5_tts_pipeline_eval.py
```

语音评测通过真实路径执行 validator -> Replay ASR -> TextEntryService -> Phase 4 -> Phase 3 -> Orchestrator -> SQLite/PostgreSQL repositories，并从真实结果/数据库独立比较 expected 字段。

## 当前基线

| 指标 | matches/checks |
|---|---:|
| audio validation | 240/240 |
| fixture hash | 240/240 |
| transcript | 184/184 |
| locale | 180/180 |
| intent | 180/180 |
| classification | 200/200 |
| item | 60/60 |
| quantity | 36/36 |
| mutation | 240/240 |
| handoff reason | 36/36 |
| refusal reason | 32/32 |
| no-speech | 4/4 |
| low-confidence | 4/4 |
| provider failure | 16/16 |
| database order | 240/240 |
| tenant isolation | 4/4 |
| audio retention | 240/240 |
| transcript logging | 240/240 |
| live provider | 240/240 |
| live LLM | 240/240 |

wrong mutation、confirmation bypass、serious allergy omission、cross-tenant leak、fake merchant acceptance、duplicate database order、raw audio persistence、full transcript log、live Provider call 和 live LLM trigger 均为 0。

TTS 的 15 条 fixture 在 text/audio hash、locale、voice、WAV、format、duration、audit、无网络和订单不变上均为 15/15；missing fixture 为 1/1。Replay 延迟只代表 CI fixture 管线，不能外推为真实 Provider 性能。

评测输出 audio validation、Replay ASR、TextEntry/安全/订单文本管线、Replay TTS 和端到端的 p50/p95/max；这些数字不构成生产 SLA。

## 独立性

专项测试验证修改 expected transcript/locale/intent/classification 不会改变 Provider 或 runtime 输出；manifest transcript 变化才会改变 Replay 输出；Provider 不读取 expected；无网络、无 live LLM、无真实 Provider。
