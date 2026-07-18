# 语音架构

## 入口与所有权

`SpeechPipelineService` 是 Phase 5 唯一音频入口。语音层只负责校验、规范化、调用 Provider、映射置信度和记录安全元数据；它不能直接调用 Orchestrator、订单服务、Handoff 服务或订单仓储。

成功转写必须调用 `TextEntryService.handle_text_message`。该服务继续拥有 locale 解析、Phase 4 canonical intent、Phase 3 SafetyDecision、Orchestrator 路由和订单写入。无语音、Provider 失败和不支持语言通过 `TextEntryService.handle_non_text_input_failure` 进入同一安全状态机，不由语音层自行修改状态。

```text
Synthetic AudioInput
  -> AudioValidator
  -> AudioNormalizer (仅提取，不转码、不重采样)
  -> SpeechProviderRegistry
  -> ReplayAsrProvider
  -> TranscriptEnvelope
  -> confidence allow-list mapping
  -> TextEntryService
  -> Phase 4 canonical multilingual parser
  -> Phase 3 SafetyDecision
  -> Orchestrator
  -> authoritative order state/database
  -> optional ReplayTtsProvider
  -> SpeechAuditService (metadata only)
```

全局语义意图仍优先于当前槽位，问句不得被当作订单修改，fallback 仍在最后。菜品、价格和配送费仍从服务层/数据库取得。任何保存订单的动作仍要求明确确认。

## Provider Registry

Provider 由配置选择，业务服务不 import 具体实现。未配置、名称无效、模拟未开启或生产选择 Replay 都稳定失败；系统不会自动回退到在线 Provider。

默认配置为 `disabled`。Replay 仅在 `APP_ENV=development|test`、`SIMULATION_DATA_ONLY=true` 和 `SPEECH_SIMULATION_ENABLED=true` 同时满足时可用。

## API 与 UI

`/api/speech/*` 只在允许模拟的开发/测试配置下可见。接口接收有明确上限的原始请求体或固定 JSON，不接受远程 URL、文件路径、设备/麦克风控制或不受控 multipart 落盘。前端面板仅由 `import.meta.env.DEV` 渲染，并持续标注 synthetic/replay/offline。

## TTS

TTS 处于权威文本结果之后。Provider 只获得最终回复文本、locale、固定 voice ID 和输出格式；不能决定 SafetyDecision、订单状态或商家状态。TTS 失败仅返回 `ttsErrorCode`，不会改变先前结果。
