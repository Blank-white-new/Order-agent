# Provider 契约

## ASR

`AsrProvider` 暴露稳定的 `name`、`capabilities()` 和 `transcribe(SpeechRecognitionRequest)`。请求包含 `AudioInput`、locale hint、会话及租户范围和 synthetic trace ID。响应 `TranscriptEnvelope` 包含：

- transcript（只在内存中用于 TextEntryService）；
- provider 名称、模式和可选请求 ID；
- overall/结构化 confidence、locale、duration、no-speech probability；
- 可选的无文本 segment 元数据和 `synthetic=true`。

Provider 不访问订单数据库，不提交订单，也不返回菜单、价格或配送费。异常必须映射为稳定公开错误，不能泄露路径、密钥、原始 payload 或堆栈。

## TTS

`TtsProvider` 暴露 `name`、`capabilities()` 和 `synthesize(SynthesisRequest)`。请求只包含权威回复文本、locale、voice ID、输出编码、采样率、trace ID 和 synthetic 标记。响应包含音频 bytes 及格式元数据。

TTS 是纯输出适配器，无权修改订单、重新解析文本或覆盖回复。

## Capabilities

能力对象明确声明 locales、encodings、sample rates、streaming、synthetic、是否需要网络及是否允许 production。Replay 的固定声明是：`REPLAY`、不 streaming、synthetic、`requires_network=false`、`production_allowed=false`。

## Registry 规则

- Provider 名称来自 `SPEECH_ASR_PROVIDER` / `SPEECH_TTS_PROVIDER`；
- `disabled` 返回 `SPEECH_PROVIDER_DISABLED`；
- 未知名称返回 `SPEECH_PROVIDER_INVALID`；
- production 或非模拟上下文使用 Replay 会被拒绝；
- 不存在在线回退、密钥配置或网络调用；
- Provider 实例只通过 Registry 取得。

Phase 5 没有可选本地模型 Provider。没有提交模型权重，也没有启动时或 CI 模型下载。
