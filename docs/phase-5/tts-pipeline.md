# TTS 管线

Phase 5 TTS 只验证输出契约和管线安全，不生成可懂自然语音。

```text
authoritative TextEntryService response
  -> SynthesisRequest(text hash, locale, voice, WAV/16 kHz)
  -> SpeechProviderRegistry
  -> ReplayTtsProvider
  -> deterministic synthetic tone WAV
  -> AudioValidator
  -> optional response bytes + metadata-only audit
```

支持 locale 为 `zh-CN`、`yue-Hant-HK`、`en-HK`，voice ID 为 reviewed manifest 中的 `replay-neutral`，输出为 16 kHz mono PCM S16LE WAV。15 个 safety-critical 文本 fixture 覆盖三种语言，每种 5 条。

TTS 只能朗读已经确定的权威回复，不能重写回复、执行 intent、调用 Orchestrator、改变 SafetyDecision、修改订单、伪造商家接受或绕过确认。若 TTS fixture 缺失或 Provider 失败，文本和订单结果保持不变；`respond` 只附加 `ttsErrorCode`。

离线评测检查 text hash、locale、voice、fixture、WAV、sample rate、mono、duration、audio hash、Provider mode、网络调用、订单不变和 audit。真实 TTS accuracy、intelligibility 和 naturalness 明确为 `not_evaluated`。
