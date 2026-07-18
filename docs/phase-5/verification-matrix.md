# Phase 5 验收矩阵

| 要求 | 实现证据 | 自动验证 |
|---|---|---|
| 音频契约与严格校验 | `backend/app/speech/contracts.py`、`audio_validator.py` | `test_audio_validator.py`、catalog validator |
| Provider interface/Registry | `provider.py`、`provider_registry.py` | `test_replay_providers.py` |
| Replay ASR/TTS 与 hash | `replay_asr_provider.py`、`replay_tts_provider.py` | provider tests、两套 eval |
| production 默认关闭/fail closed | `config.py`、`.env.example`、API guard | API/registry tests |
| 唯一 TextEntryService 路径 | `speech_pipeline_service.py` | pipeline、安全集成与 240 场景 eval |
| Phase 3 SafetyDecision 无旁路 | TextEntryService non-text failure entry | pipeline/evaluator tests |
| 确认前不落单 | 原 Orchestrator/订单规则不变 | 240 mutation/database checks、Phase 0–4 回归 |
| no-speech/low-confidence/failure 不误修改 | confidence mapping + stable failures | 4/4、4/4、16/16 |
| TTS 不改变订单 | output-only synthesis | TTS order unchanged 15/15 |
| 音频和 transcript 不保留 | in-memory pipeline、metadata allow-list | retention/log checks 240/240 |
| SpeechTurn 审计与租户约束 | migration/model/repository | audit、migration、tenant-negative tests |
| 240 synthetic fixtures / 4 locales | dataset/manifests/generator | validator：60/locale |
| malformed/hash mismatch | strict validator + SHA lookup | 检测率 100% |
| 开发 API/前端标注 | speech router + dev-only panel | API/Vitest/typecheck/build |
| 无网络/模型/live Provider/live LLM | Replay capabilities + offline guards | live checks 240/240、audit tooling |
| SQLite/PostgreSQL | UOW/migration/repositories | 本地 SQLite + PostgreSQL CI |
| 全量回归 | `scripts/check_all.ps1` | Windows CI + PostgreSQL CI |

## 阻断条件

以下任一非零即失败：wrong mutation、confirmation bypass、serious allergy omission、fake merchant acceptance、duplicate DB order、cross-tenant leak、raw audio persistence、full transcript logging、live Provider calls、live LLM triggers。

## 明确非目标

真实电话、PSTN/SIP/RTP/WebRTC、真实 ASR/TTS Provider、真实顾客录音、streaming、barge-in、G.711、真实人工坐席、POS、支付、商家接受、生产凭证、真实语音准确率和 TTS 自然度均未实现。
