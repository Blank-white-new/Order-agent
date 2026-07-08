# 语音演示与排障

语音输入和 TTS 是本机演示能力，不是云端托管承诺。ASR 依赖本地 Vosk 模型和麦克风；server-side pyttsx3 从运行 FastAPI 的机器播放。

## 最小演示配置

```env
VOICE_ENABLED=true
VOSK_MODEL_PATH=./models/asr/vosk-cn
TTS_ENABLED=true
TTS_PLAYBACK_TARGET=server
```

配置只保存在本机 `.env`，不要提交。前端中的“语音服务状态（调试）”默认折叠，普通 demo 只需要确认录音和播报显示可用。

## 排障顺序

1. 调用 `GET /api/voice/status`，确认录音/播报能力。
2. 检查浏览器麦克风权限和 Vosk 模型路径。
3. TTS 显示成功但无声时，确认声音是否应从 FastAPI 所在机器播放。
4. 需要链路诊断时，临时设置 `VITE_DEBUG_VOICE=true` 和 `VOICE_DEBUG=true`，重启服务后查看日志。
5. 复测结束后关闭 debug，避免技术信息干扰公开演示。

更细的 Auto TTS A–J 分类与复测模板仍保留在 README 的折叠历史参考中。
