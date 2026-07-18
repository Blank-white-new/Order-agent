# Replay Provider

## Replay ASR

Replay ASR 是确定性测试双，不做语音识别。它要求：

1. `fixture_id` 存在于 `phase5_asr_manifest.jsonl`；
2. 请求音频的 SHA-256 与该 fixture 的 reviewed manifest 相同；
3. manifest 的编码、MIME、sample rate、channels 和 sample width 与请求相同；
4. outcome 为成功时，返回 manifest 的权威 transcript、locale 和 confidence；
5. outcome 为 no-speech、timeout、error、truncated 或 unsupported language 时，返回对应稳定失败。

评测 JSONL 中的 expected transcript/locale/intent 只用于独立比较，Provider 不读取评测 expected 字段。修改 expected 值不会改变 Replay 输出。

## Replay TTS

Replay TTS 同样不合成自然语音。它以 `SHA-256(text)`、locale、voice ID、编码和 sample rate 查找 reviewed manifest，然后返回仓库中的确定性 tone WAV。不存在映射时稳定返回 fixture not found。

## 来源与可重复性

全部 WAV 由 `scripts/generate_phase5_audio_fixtures.py` 使用 Python 标准库生成，`provenance=deterministic-synthetic-tone-v1`。没有真人声音、未知许可素材或模型生成语音。`scripts/validate_phase5_audio_catalog.py` 校验安全相对路径、schema、hash、locale 分布、重复内容和 manifest 一致性。

## 边界

Replay Provider：

- 不访问网络；
- 不下载或加载语音模型；
- 不访问订单数据库；
- 不接受真实 Provider key；
- 不允许 production；
- 不证明真实 ASR accuracy、TTS intelligibility 或 naturalness。
