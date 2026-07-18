# ASR confidence 策略

Replay manifest 可以给出 overall confidence，以及 intent、item、quantity、modifier、address、phone confidence 和 contradictory fields。语音管线只把这一白名单映射给 `TextEntryService`；其它 Provider 字段被丢弃。

有效 confidence 是已提供结构化 confidence 与 overall confidence 的最小值：

- `>= 0.65`：可继续正常文本安全决策，但下单仍需明确确认；
- `0.35–0.65`：`LOW_CONFIDENCE`，由 Phase 3 规则选择 clarification/confirm/handoff，不能静默修改订单；
- `< 0.35`：进入更保守的 Phase 3 handoff 处理；
- no-speech probability `>= 0.90`：`NO_SPEECH_DETECTED`，不解析 transcript、不修改订单；
- 连续低 confidence 上限为 2，之后安全升级，状态仍由 TextEntryService/SafetyDecision 维护。

阈值由 `SPEECH_CONFIRM_THRESHOLD`、`SPEECH_HANDOFF_THRESHOLD`、`SPEECH_NO_SPEECH_THRESHOLD` 和 `SPEECH_MAX_CONSECUTIVE_LOW_CONFIDENCE` 配置并校验。

这些值只用于验证状态机行为，不是经过真实 ASR 校准的概率，也不能被报告成普通话、粤语或英语识别准确率。音频问句仍按全局问句意图处理，不会因为 confidence 高而修改订单；过敏、缺货、地址/电话矛盾等 Phase 3 安全规则始终优先。
