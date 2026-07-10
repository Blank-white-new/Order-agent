# Demo Capture Checklist

本 checklist 用于录制 30-60 秒公开演示素材。不要伪造截图、GIF 或语音结果。

## 录制前

- 从 `feature/demo-assets-and-voice-acceptance` 或最新已验证分支启动。
- 保持 `.env` 不提交，且公开 demo 保持 `LLM_FALLBACK_MODE=disabled`、`LLM_FALLBACK_ENABLED=false`。
- 不在画面中展示真实 API key、终端凭据、真实手机号、真实地址或个人隐私。
- 使用示例电话时只用 `13800000000`，并优先展示前端掩码 `138****0000`。
- 保持调试信息和语音服务状态默认折叠，除非正在录制排障说明。

## 启动服务

终端 A：

```powershell
cd <repo>\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端 B：

```powershell
cd <repo>\frontend
npm run dev
```

打开：

```text
http://127.0.0.1:3000/
```

## 文本 demo 录制脚本

点击“新订单”，依次输入：

1. `推荐一下`
2. `第一个来一份`
3. `再来一份可乐`
4. `把可乐删掉`
5. `我要配送到中山大学南校园，电话是 13800000000`
6. `确认订单`

画面重点：

- 推荐候选出现
- 第一个推荐项进入右侧订单摘要
- `可乐` 先加入再删除
- 地址进入配送状态
- 电话显示为 `138****0000`
- 提交后显示 `mock order` 订单号
- 提交后旧订单不可继续修改

建议截图文件：

- `docs/assets/demo-chat-order.png`
- `docs/assets/demo-flow.gif`

## 语音链路人工验收

只有在 `/api/voice/status` 显示 `voiceEnabled=true` 且 `canRecord=true` 后，才录制语音素材。

环境条件：

- Vosk 中文模型已解压到 `models/asr/vosk-cn/`
- 浏览器麦克风权限已允许
- 本机麦克风可用
- 如需播报，Windows 中文 TTS、扬声器或耳机可用
- FastAPI 与浏览器运行在同一台可播放音频的机器上，或已确认 server-side TTS 的播放位置

人工验收流程：

1. 点击“开始说话”，说：`我要一份鸡腿饭。`
2. 确认识别文本出现，助手回复出现，右侧订单摘要显示 `鸡腿饭 x1`
3. 继续说：`改成两份。`
4. 确认右侧摘要变成 2 份
5. 继续说：`不要了。`
6. 确认订单摘要减少或清空
7. 继续说：`我要配送到中山大学南校园，电话是 13800000000。`
8. 确认地址进入状态，电话掩码显示
9. 播报期间点击“开始说话”，观察是否有明显回声、异常音量变大或订单状态误修改

建议语音素材文件：

- `docs/assets/demo-voice-state-sync.png`
- `docs/assets/demo-flow.gif`

若任一条件不满足，只记录未测试原因，不补假素材。
