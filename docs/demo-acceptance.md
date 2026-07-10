# Demo Acceptance

本记录用于把新电脑上的 demo 状态从“测试通过”推进到“可以稳定演示”。记录日期：2026-07-10。

## 环境与分支

- 项目目录：仓库根目录 `order_system_public`
- 起始 main HEAD：`af3bbbb7e3ea2f055047a44f22a6911b58cd5479`
- 阶段分支：`feature/demo-assets-and-voice-acceptance`
- 真实 LLM：未调用
- 真实 API key：未使用、未输出、未提交
- `.env`：仅本机文件，未被 Git 跟踪；`LLM_FALLBACK_ENABLED=false`

## 基础验证

从项目根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
.\scripts\check_all.ps1 -Build
.\backend\.venv\Scripts\python.exe -B evaluation\run_dialogue_eval_v3.py --dataset evaluation\dialogues_v3.jsonl
```

结果：

- pytest：798 passed
- `check_all.ps1 -Build`：通过
- V3 eval：57/57，false mutation 0，confirmation bypass 0，llm trigger count 0

## 本机服务 smoke

后端按 README 命令启动：

```powershell
cd .\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

验证结果：

- `GET http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}`
- 后端日志显示语音默认关闭：`voice config: enabled=False`
- smoke 期间 `/api/menu`、`/api/voice/status`、`/api/reset`、`/api/chat` 均返回 200

前端按 README 命令启动：

```powershell
cd .\frontend
npm run dev
```

验证结果：

- Vite 输出本机地址：`http://127.0.0.1:3000/`
- 页面正常加载菜单、聊天区、订单摘要和语音控件
- 浏览器 console 无 error/warn
- 前端默认连接 `http://localhost:8000/api`，文本交互可达后端

## 文本 demo 验收

### 流程 A：推荐并点单

输入：

1. `推荐一下`
2. `第一个来一份`
3. `再来一份可乐`
4. `把可乐删掉`
5. `查看订单`

结果：通过。

- 推荐返回 `鸡腿饭`、`番茄鸡蛋面`、`宫保鸡丁饭`
- `第一个来一份` 加入 `鸡腿饭 x1`
- `可乐` 可以加入并删除
- `查看订单` 后右侧摘要只保留 `鸡腿饭 x1`，总价 26 元
- 调试信息默认折叠，不阻断公开演示

### 流程 B：配送信息和确认

输入：

1. `我要配送到中山大学南校园，电话是 13800000000`
2. `确认订单`

结果：通过。

- 配送地址进入订单状态
- 电话在订单摘要中显示为 `138****0000`
- 提交后显示 `订单号（mock order）：MOCK-ORDER-0001`
- 额外发送 `再来一份可乐` 时，系统回复已提交订单不能继续修改，右侧订单未变化

### 流程 C：误修改防护

提交后点击“新订单”开始干净会话，再输入：

1. `鸡腿饭听起来不错`
2. `黑椒牛肉饭有优惠吗`
3. `第一个不要了`

结果：通过。

- 陈述句未加菜，系统澄清是否要点 `鸡腿饭`
- 问句只返回 `黑椒牛肉饭` 价格信息，未加菜
- 歧义指代返回澄清：“这里的‘第一个’可能指推荐，也可能指订单”
- 右侧订单状态保持空单，无错误 mutation

## 语音人工验收

本机未做真实麦克风链路验收，原因是后端语音未开启，且 Vosk 模型目录未配置。

`GET /api/voice/status` 结果摘要：

- `voiceEnabled=false`
- `canRecord=false`
- `canSpeak=false`
- `asrDependencyAvailable=true`
- `ttsDependencyAvailable=true`
- `modelPathExists=false`
- `modelLooksValid=false`

需要满足以下条件后再验收真实语音：

- `.env` 中设置 `VOICE_ENABLED=true`
- 下载并解压 Vosk 中文模型到 `models/asr/vosk-cn/`
- 浏览器允许麦克风权限
- 本机有可用麦克风
- 如需播报，确认 Windows 中文 TTS、扬声器或耳机可用
- 重启 FastAPI 后端，并确认 `/api/voice/status` 中 `canRecord=true`

待人工复测流程见 [演示素材录制 checklist](demo-capture-checklist.md)。

## 演示素材

已新增真实安全截图：

- `docs/assets/demo-chat-order.png`

截图内容只包含文本 demo 中的菜品推荐和订单摘要，不包含真实电话、真实地址、API key、`.env` 内容或本机私人凭据。
