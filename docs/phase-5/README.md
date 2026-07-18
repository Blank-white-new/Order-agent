# Phase 5：语音 Provider 契约与离线评测

Phase 5 为普通话、粤语、香港英语和混合语言增加严格离线、可审计的合成语音入口。它验证音频容器、Provider 契约、错误处理、`TextEntryService` 集成、Phase 3 `SafetyDecision` 和数据库订单语义，不代表真实 ASR/TTS 能力。

## 已实现

- 单声道 PCM S16LE 与 WAV/PCM S16LE 的严格校验和无损提取；
- 集中式 ASR/TTS Provider Registry，默认关闭且 fail closed；
- 基于 fixture ID、音频 SHA-256 和审阅清单的 Replay ASR；
- 基于文本 SHA-256 和确定性合成波形的 Replay TTS；
- 唯一音频入口 `SpeechPipelineService`，成功 transcript 只进入 `TextEntryService`；
- 只保存白名单元数据的 `speech_turn_records` 审计表；
- development/test 专用 API 和开发态前端回放面板；
- 240 条离线音频场景，以及独立的 ASR/TTS 评测。

评测器使用调用观察器记录每次真实 `transcribe`/`synthesize` 调用及 lookup、hash、metadata 阶段。validation 已失败的 28 条场景不会进入 Provider 分母；fixture missing、hash mismatch 和正常 Replay 分别停在真实执行到的阶段。审计记录存在性、数据库音频持久化、临时文件、transcript 日志和租户隔离分别计算，互不替代。

无 transcript 的日志证据继续分层：52 条确实存在 expected/manifest transcript 候选的失败场景检查候选文本未泄漏；4 条 fixture-not-found 没有任何 transcript 候选，改为检查稳定错误、日志/trace 结构、绝对路径、manifest、其他 fixture transcript/ID、audio payload、订单记录和失败审计，不再由空集合 `all()` 自动通过。

网络指标仅表示 Replay ASR/TTS Provider 调用路径没有尝试四个受控 Python 网络入口。它不声称整个评测进程没有网络活动，也不覆盖 PostgreSQL、GitHub Actions、pip/npm 或非 Provider 代码。

## 安全边界

Replay Provider 不是实际 ASR/TTS。本阶段未接真实电话、在线 Provider、真实顾客录音或模型下载；不评估真实识别准确率、TTS 可懂度或自然度。生产默认关闭模拟端点，音频和完整 transcript 均不持久化。

订单语义链路固定为：

```text
AudioValidator -> AudioNormalizer -> ReplayAsrProvider
-> TextEntryService -> Phase 4 canonical parsing
-> Phase 3 SafetyDecision -> Orchestrator -> order persistence
```

TTS 只读取已经形成的权威回复；TTS 失败不得回滚或推进订单。任何下单仍必须明确确认，Replay transcript 也不能绕过确认。

## 验证

```powershell
.\backend\.venv\Scripts\python.exe -B scripts\validate_phase5_audio_catalog.py
.\backend\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider backend\tests\phase5
.\backend\.venv\Scripts\python.exe -B evaluation\run_phase5_speech_pipeline_eval.py
.\backend\.venv\Scripts\python.exe -B evaluation\run_phase5_tts_pipeline_eval.py
.\scripts\check_all.ps1 -Build
```

详细说明：

- [语音架构](speech-architecture.md)
- [Provider 契约](provider-contracts.md)
- [音频格式](audio-formats.md)
- [音频安全](audio-security.md)
- [ASR confidence 策略](asr-confidence-policy.md)
- [Replay Provider](replay-provider.md)
- [TTS 管线](tts-pipeline.md)
- [数据保留](data-retention.md)
- [离线评测](evaluation.md)
- [验收矩阵](verification-matrix.md)
- [完成审计](completion-audit.md)

Phase 6 的进入条件是先完成法律、隐私、威胁建模和 Provider 沙箱评审，再考虑电话媒体管线或真实 Provider；本 PR 不提前实现这些能力。
