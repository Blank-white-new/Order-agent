# 音频格式

## 支持

| 项目 | Phase 5 限制 |
|---|---|
| 编码 | `PCM_S16LE`、`WAV_PCM_S16LE` |
| bit depth | 16-bit signed little-endian |
| channels | 1（mono） |
| sample rate | 8,000 Hz 或 16,000 Hz |
| 时长 | 100–30,000 ms（含边界） |
| 最大请求 | 960,044 bytes |
| WAV MIME | `audio/wav`、`audio/x-wav`、`audio/wave` |
| raw PCM MIME | `audio/l16`、`audio/pcm`、`application/octet-stream` |

WAV 必须为 RIFF/WAVE，具有唯一、结构正确的 PCM `fmt ` 和 `data` chunk；`audioFormat=1`、block align/byte rate/RIFF 长度必须一致。未知 chunk、重复关键 chunk、截断、尾随字节、奇数 PCM 长度和声明/容器元数据不一致均被拒绝。

## 不支持

MP3、AAC、Opus、FLAC、G.711 μ-law/A-law、stereo、多声道、浮点 PCM、24/32-bit PCM、压缩 WAV、streaming、分片上传和自动转码均不支持。`AudioNormalizer` 只从已验证容器提取 PCM，不重采样、不转码，也不创建临时文件。

## 稳定错误代码

校验器使用 `AUDIO_*` 代码覆盖空 payload、过大、MIME/编码不支持、sample rate、channels、sample width、WAV header/chunk、长度、时长、静音和截断等失败。Provider/管线另使用 `SPEECH_FIXTURE_HASH_MISMATCH`、`NO_SPEECH_DETECTED`、`SPEECH_TIMEOUT`、`SPEECH_PROVIDER_FAILURE` 和 `SPEECH_LANGUAGE_UNSUPPORTED`。
