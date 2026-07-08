# Multi-Agent Ordering System

一个规则优先、Orchestrator 统一裁决的中文多 Agent 订餐演示系统。它覆盖多轮点餐、推荐、订单修改、配送/自取与提交确认，并提供 React 前端、可选语音演示、安全 LLM fallback sandbox 和可重复的 V3 对话评估。

> 默认运行不调用真实 LLM。菜单、价格与配送费来自服务层；订单提交前必须确认，所有状态修改都经过 Orchestrator。

## 项目亮点

- 规则优先的中文语义路由，多轮上下文和问句防误修改。
- 文本与语音共用订单状态；支持推荐、换菜、数量修改、配送、自取和确认。
- ASR、文本归一化、TTS 与 barge-in 可用于本机演示。
- LLM fallback 提供 disabled/fake/replay/shadow 安全模式，live 默认不可用。
- V3 对话集当前基线 57/57，持续检查误修改与确认绕过。
- 后端 pytest、前端 Vitest/TypeScript/build 可通过一个脚本完成。

## 功能矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 文本点餐 | 已支持 | 多轮加菜、改数量、删除和换菜 |
| 推荐 | 已支持 | 基于菜单、偏好和预算生成候选 |
| 配送/自取 | 已支持 | 地址、电话和 mock 配送费均由服务层处理 |
| 订单确认 | 已支持 | 提交前确认；submitted 后锁定旧订单 |
| 语音输入 | 演示支持 | 本机 ASR、normalizer 和 barge-in |
| TTS | 本机演示支持 | server-side pyttsx3 受运行机器音频环境限制 |
| LLM fallback | sandbox 支持 | 默认 disabled，不直接提交或绕过 validation |
| V3 eval | 已支持 | 当前 57/57 离线基线 |

架构、录屏流程和专项说明：

- [系统架构](docs/architecture.md)
- [30–60 秒演示脚本](docs/demo-guide.md)
- [LLM fallback sandbox](docs/llm-sandbox.md)
- [语音演示与排障](docs/voice-troubleshooting.md)

## 快速开始（Windows PowerShell）

1. 克隆项目并进入目录：

```powershell
git clone https://github.com/Blank-white-new/Order-agent.git
cd Order-agent
```

2. 可选：复制本机配置。纯文本 demo、测试和 V3 eval 不需要真实 LLM key：

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env` 只放本机配置，绝不要提交。公开 demo 请保持 `LLM_FALLBACK_MODE=disabled`；文本订餐主流程和测试不需要 API key。

3. 安装后端依赖：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

4. 安装前端依赖：

```powershell
cd ..\frontend
npm install
```

5. 启动后端（一个 PowerShell 窗口，从仓库根目录执行）：

```powershell
cd .\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

6. 启动前端（另一个 PowerShell 窗口，从仓库根目录执行）：

```powershell
cd .\frontend
npm run dev
```

默认前端请求 `http://localhost:8000/api`。打开：

```text
http://127.0.0.1:3000
```

如果希望本地开发走同源 `/api`，启动前端前设置：

```powershell
$env:VITE_API_BASE_URL="/api"
$env:VITE_BACKEND_PROXY_TARGET="http://localhost:8000"
npm run dev
```

7. 在仓库根目录运行一键检查（脚本强制离线，不调用真实 LLM）：

```powershell
.\scripts\check_all.ps1 -Build
```

8. 可选开启语音和调试：

```env
VOICE_ENABLED=true
VOICE_DEBUG=true
VOSK_MODEL_PATH=./models/asr/vosk-cn
TTS_ENABLED=true
TTS_PLAYBACK_TARGET=server
```

前端语音调试日志可在启动前端前设置：

```powershell
$env:VITE_DEBUG_VOICE="true"
```

<details>
<summary>历史 Auto TTS 链路诊断参考（默认折叠）</summary>

## Auto TTS 真实链路复测 v12

本节用于定位“测试播报有声音，但真实语音点餐的 agent_reply 没有自动播报”的链路问题。这里的诊断增强只帮助定位，不代表真实播报已经修复完成；真实结果必须以本机浏览器、麦克风和人工听感复测为准。

### 开启诊断

前端浏览器日志：

```env
VITE_DEBUG_VOICE=true
```

修改前端 `.env` 或启动环境后，必须重启 Vite dev server。打开浏览器 DevTools Console，过滤 `voice-debug`，复制 `[voice-debug] start_utterance`、`stop_utterance`、`final`、`agent_reply`、`tts_status`。

后端 auto TTS 日志：

```env
VOICE_DEBUG=true
```

修改后端 `.env` 或环境变量后，必须重启 FastAPI。查看后端控制台中的 `[voice-auto-tts]`。日志只记录 id、长度、短 preview、queue 结果和跳过原因，不记录完整文本、trace、音频、API key 或敏感路径。

状态查询：

```text
GET http://localhost:8000/api/voice/tts/status
```

重点记录 `runtimeId`、`runnerId`、`jobHistory`、`latestManualJob`、`latestAutoJob`。`/api/voice/tts/status` 是只读状态查询，不会初始化 runner，不会触发 TTS，也不会修改 `jobHistory`。

证据来源：

- 浏览器 DevTools Console：`[voice-debug]`
- 浏览器 Network -> WebSocket Frames：`start_utterance`、`stop_utterance`、`final`、`agent_reply`、`tts_status`
- 后端控制台：`[voice-auto-tts]`
- `GET /api/voice/tts/status`
- 人工听感：是否实际听到 agent_reply 播报

### A-J 分类指南

- `start_utterance.tts_enabled` 不是 `true` -> A
- 前端 `tts_enabled=true`，但后端无 `preference_saved` -> B
- start/stop/final 的 `utterance_id` 不一致 -> C
- 有 `agent_reply`，但无 `queue_tts_called` -> D
- `queue_tts_called=true`，但 `queued=false` -> E
- `queue_tts` 返回 `queued=true`，但无 `[voice-debug] tts_status` -> F
- `tts_status.queued=true`，但 `jobHistory` 无同 `job_id` -> G
- `jobHistory` 有 `source=auto` 但 `status=failed` -> H
- `jobHistory` 有 `source=auto` 且 success，但没声音 -> I
- manual 与 auto 的 `runtimeId/runnerId` 不一致 -> J

### 用户复测提交模板

```text
测试播报是否有声：
status before runtimeId：
status before runnerId：
before job ids：
manual job_id：
manual job status：
start_utterance.utterance_id：
start_utterance.tts_enabled：
stop_utterance.utterance_id：
是否收到 final：
是否收到 agent_reply：
是否收到 tts_status：
tts_status.queued：
tts_status.reason：
tts_status.job_id：
status after job ids：
是否新增 source=auto job：
auto job status：
auto job success：
是否实际听到 agent_reply 播报：
```

</details>

用户通过聊天完成看菜单、推荐、点餐、配送咨询、地址确认和订单确认；所有状态修改都由 Orchestrator 统一裁决。

## 多 Agent 架构

请求统一进入 `OrchestratorAgent.handle_user_message()`：

1. 规范化输入
2. 调用 `SemanticRouterAgent`
3. 在低置信场景可进入默认离线的 LLM fallback sandbox
4. 按全局语义优先级选择子 agent
5. 接收子 agent 的 `actionResult` 与 `proposedStatePatch`
6. 校验状态修改不变量
7. 更新 session state
8. 调用 `ResponseAgent` 输出自然语言回复
9. 返回 `response`、`state`、`trace`

## Agent 职责

- `OrchestratorAgent`：唯一统一入口，负责路由、状态补丁校验和 trace。
- `SemanticRouterAgent`：规则优先解析意图、实体、偏好和是否允许修改订单。
- `MenuAgent`：回答菜单、价格、可选项、酒水、订单摘要问题。
- `RecommendationAgent`：从真实菜单推荐 2-3 个菜，并保存 `last_recommendations`。
- `OrderAgent`：处理加菜、选择推荐、修改偏好、删除菜品。
- `DeliveryAgent`：处理配送时长、配送费、能否送达、地址和电话收集。
- `ContextRepairAgent`：处理“我还没点”“你理解错了”等纠错表达。
- `ConfirmationAgent`：校验并提交订单。
- `ResponseAgent`：只把 action result 转成简短自然回复，不改状态。

## 安装依赖

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置 `.env`

复制 `.env.example` 为 `.env` 后按需填写自己的 DeepSeek / LLM fallback 配置。不要提交真实 `.env`。

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro

LLM_FALLBACK_MODE=disabled
LLM_FALLBACK_ENABLED=false
ALLOW_LIVE_LLM=false
LLM_FALLBACK_PROVIDER=deepseek
LLM_FALLBACK_BASE_URL=https://api.deepseek.com
LLM_FALLBACK_MODEL=deepseek-chat
LLM_FALLBACK_API_KEY=
```

`LLM_FALLBACK_MODE=disabled` 是默认值。pytest、`check_all.ps1` 和 V3 eval 都强制离线；本阶段请使用 fake/replay/shadow 做安全验证，不要在普通开发流程开启 live。模式、回放 fixture 和 shadow eval 用法见 [LLM fallback sandbox](docs/llm-sandbox.md)。更多后端、前端、ASR、TTS 变量见 `.env.example`。

## 启动后端

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

接口：

- `GET /api/health`
- `GET /api/menu`
- `POST /api/chat`
- `POST /api/reset`

## 启动前端

```powershell
cd frontend
npm install
npm run dev
```

前端默认请求 `http://localhost:8000/api`。

如果希望本地开发走同源 `/api`，可以启用 Vite dev proxy：

```powershell
cd frontend
$env:VITE_API_BASE_URL="/api"
npm run dev
```

Vite 会把 HTTP 和 WebSocket 的 `/api` 请求代理到后端，默认目标是 `http://localhost:8000`。如果后端端口不同，可以设置：

```powershell
$env:VITE_BACKEND_PROXY_TARGET="http://localhost:8001"
```

## 运行测试

```powershell
cd backend
pytest -q
```

测试覆盖语义路由、菜单 agent、配送 agent、订单 agent、上下文修复、确认提交和 fallback/smalltalk。

普通 pytest、`check_backend.ps1` 和 `check_all.ps1` 会强制使用离线 LLM 配置，不读取项目 `.env` 中的 provider 凭据。fake/replay/shadow 都不发起真实 provider 请求；live 需要另行安全评审。

## 一键质量验证

提交前建议从项目根目录运行：

```powershell
.\scripts\check_backend.ps1
.\scripts\check_frontend.ps1
.\scripts\check_all.ps1
.\scripts\check_all.ps1 -Build
```

脚本含义：

- `.\scripts\check_backend.ps1`：运行后端全量 `pytest`。
- `.\scripts\check_frontend.ps1`：运行前端 Vitest 和 TypeScript 检查。
- `.\scripts\check_all.ps1`：依次运行后端 pytest、前端 Vitest、前端 TypeScript 检查。
- `.\scripts\check_all.ps1 -Build`：在上述检查后额外运行前端 production build。

前端 build 会生成 `frontend/dist/`。这是本地构建产物，默认不提交，已被 `.gitignore` 忽略。

如果只想分别验证，也可以单独运行：

```powershell
.\scripts\check_backend.ps1
.\scripts\check_frontend.ps1
.\scripts\check_frontend.ps1 -Build
```

## DeepSeek / LLM fallback 配置

`DEEPSEEK_MODEL` 仍用于兼容旧 DeepSeek 配置。LLM fallback 使用独立的 `LLM_FALLBACK_*` 配置，默认 `LLM_FALLBACK_MODE=disabled`。

fallback 只在规则返回 fallback/unknown、低置信或明确理解失败时尝试；确定性高置信规则命中不会调用 LLM。LLM 只做低置信兜底理解和候选动作抽取，不直接修改订单、不直接提交订单、不绕过 `ConfirmationAgent`。菜单项、价格和配送费仍必须来自服务层。

`LLMClient` 只读取环境变量或项目 env 配置，不硬编码 API Key。测试使用 mock/fake client，不会真实调用 DeepSeek 或其他外部 LLM API。不要提交 `.env`、`.env.local`、其他真实 env 文件或真实 key。

## Trace 查看

`POST /api/chat` 每轮都会返回 `trace`，包含：

- 最终 intent 和 selected agent
- fallback 是否使用
- LLM fallback 是否启用、配置、触发、降级、耗时和校验结果
- 状态修改是否允许
- 当前订单、地址、pending candidate 的前后变化
- 最终回复

前端只在消息下方提供默认折叠的“调试信息”，普通演示不会直接展开 trace。

## 推荐演示脚本

### 演示 1：完整下单

逐句输入：

```text
招牌菜是啥
黑椒牛肉饭吧
再来一份
这个少辣
配送
中山大学南校园
13800000000
确认
```

预期结果：

- 订单中有黑椒牛肉饭，数量为 2。
- `少辣` 进入该菜品的 `options`。
- 配送地址记录为演示地址中山大学南校园。
- 电话仅使用示例号码 `13800000000`，前端显示为 `138****0000`。
- 最终确认后提交成功，状态进入 `submitted`。

### 演示 2：自然修改

逐句输入：

```text
牛肉饭
换成鸡腿饭
这个少辣
加一瓶可乐
不要可乐了
配送
中山大学南校园
13800000000
确认
```

预期结果：

- 牛肉饭被替换成鸡腿饭。
- 鸡腿饭保留 `少辣` 选项。
- 可乐先加入后移除。
- 地址、电话完整后可以确认提交。

### 演示 3：pending 安全

逐句输入：

```text
牛肉饭
不要了
鸡腿饭多少钱
确认
```

预期结果：

- `不要了` 只产生清空订单的待确认动作，不会立即清空。
- 问价后旧清空 `pending_action` 失效。
- 后续 `确认` 不会触发旧清空动作，也不会误清空订单。

### 演示 4：备注

逐句输入：

```text
牛肉饭
这个不要香菜
```

预期结果：

- 不新增第二份菜。
- `不要香菜` 写入 `OrderItem.notes`。
- 后续确认摘要中显示备注。

## 语音/TTS 说明与限制

- 当前 ASR 通过后端 WebSocket `/api/voice/asr` 接入。
- 浏览器采集麦克风音频后发送给后端 ASR；后端返回 partial/final transcript。
- final transcript 会进入现有文本订餐主流程，也就是仍由 Orchestrator 统一路由和修改订单状态。
- 当前 TTS 是 server-side TTS，默认 provider 为 `pyttsx3`。
- `TTS_PLAYBACK_TARGET=server` 时，声音从运行 FastAPI 的机器播放，不是从浏览器标签页播放。
- 如果用户用远程浏览器访问，可能听不到服务器本机播放的声音。

如果 TTS 状态显示成功但本机无声，优先检查：

- 系统音量是否过低或静音。
- 当前输出设备是否正确。
- Windows 应用音量/静音设置。
- `pyttsx3` 是否可用，Windows 是否安装了中文语音。
- `GET /api/voice/tts/status` 中的 `lastSuccess`、`lastError`、`maybeStuck`、`currentVoice`。
- FastAPI 是否真的运行在有音频输出的机器上，而不是 WSL、Docker、远程服务器或无声卡环境。

## 本地语音功能

语音功能通过 `VoiceGatewayAgent` 接入。它只是语音 I/O 网关：负责 ASR、TTS、语音轮次状态、utterance 去重和文本转发，不参与点餐决策，不直接修改订单，也不进入业务路由。所有 final transcript 都会转交现有文本入口，再由 Orchestrator 和各业务 agent 处理。

默认关闭：

```env
VOICE_ENABLED=false
```

开启 Web 语音模式：

```env
VOICE_ENABLED=true
ASR_ENGINE=vosk
VOSK_MODEL_PATH=./models/asr/vosk-cn
TTS_ENABLED=true
TTS_ENGINE=pyttsx3
TTS_PLAYBACK_TARGET=server
TTS_ENGINE_RECREATE_PER_TASK=true
```

前端会使用浏览器麦克风采集音频，通过 WebSocket 发送 `16kHz mono signed 16-bit little-endian PCM` 到 `/api/voice/asr`。服务端返回 `partial`、`final`、`agent_reply`、`status`、`error` 等 JSON 消息。`partial` 只显示；只有 `final` 会触发文本订餐入口。后端已处理 final 后，前端不会再额外调用 `/api/chat`。

下载 Vosk 中文模型：

1. 到 Vosk 官网下载中文模型，例如 `vosk-model-small-cn-*`。
2. 解压到 `models/asr/vosk-cn/`。
3. 确认目录里包含 Vosk 模型文件，而不是多套一层压缩包目录。

安装语音依赖：

```powershell
cd backend
pip install -r requirements.txt
```

`vosk` 和 `pyttsx3` 都是 lazy import：`VOICE_ENABLED=false` 时，即使没有安装语音依赖，文本模式仍应正常启动和测试。本轮不实现 CLI 语音模式，因此不强制依赖 `sounddevice`；Web 麦克风采集由浏览器 `getUserMedia` 完成。

TTS 说明：

- 第一阶段只支持 `TTS_PLAYBACK_TARGET=server`。
- 这表示声音从运行 FastAPI 后端的本机播放。
- 如果后端运行在 WSL、Docker、远程服务器，或不是浏览器所在机器，浏览器端可能听不到后端 `pyttsx3` 的声音。
- `TTS_PLAYBACK_TARGET=browser` 仅预留，后续可扩展。

Windows 注意事项：

- 确认系统隐私设置允许浏览器访问麦克风。
- 首次点击“开始说话”时，浏览器会弹出麦克风权限请求。
- 如果没有中文 TTS 声音，需要在 Windows 语音设置里安装中文语音包，或暂时关闭 `TTS_ENABLED`。

常见问题：

- 找不到 Vosk 模型：检查 `VOSK_MODEL_PATH`，`/api/voice/status` 会返回清晰错误。
- 麦克风权限不足：检查浏览器地址栏权限和 Windows 隐私设置。
- `vosk` 安装失败：确认 Python 版本和 pip 源，或先保持 `VOICE_ENABLED=false` 使用文本模式。
- 没有中文 TTS 声音：安装系统中文语音，或设置 `TTS_ENABLED=false`。
- TTS 回声与打断：用户已点击“开始说话”进入录音轮次时，TTS speaking 不再阻断 ASR；如果播报中点击“开始说话”，前端会先调用 `POST /api/voice/tts/stop` 做 best-effort 停止并清空待播队列，再录入本轮语音。`pyttsx3` 是否能立即停声取决于系统语音驱动。
- 语音识别不准但文本 agent 正常：这是 ASR 模型问题；可以直接使用文本框，或更换更大的 Vosk 中文模型。

语音接口：

- `GET /api/voice/status`
- `WebSocket /api/voice/asr?session_id=...`
- `POST /api/voice/tts`
- `POST /api/voice/tts/stop`
- `GET /api/voice/tts/status`

### 让本地语音功能可用

1. 安装后端依赖：

```powershell
python -m pip install -r backend/requirements.txt
```

2. 下载 Vosk 中文模型。推荐开发使用 `vosk-model-small-cn-0.22`，下载页是 `https://alphacephei.com/vosk/models`。不要把模型文件提交到 Git。

3. 解压模型到：

```text
models/asr/vosk-cn/
```

解压后的目录应直接包含 `conf/`、`am/`、`graph/`，以及可选的 `ivector/`。空目录或多套一层压缩包目录都不能让 `canRecord=true`。

4. 在项目根目录 `.env` 中配置：

```env
VOICE_ENABLED=true
ASR_ENGINE=vosk
VOSK_MODEL_PATH=./models/asr/vosk-cn
ASR_SAMPLE_RATE=16000
ASR_LANGUAGE=zh-cn
TTS_ENABLED=true
TTS_ENGINE=pyttsx3
TTS_RATE=180
TTS_VOLUME=1.0
TTS_PLAYBACK_TARGET=server
TTS_ENGINE_RECREATE_PER_TASK=true
```

5. 运行自检脚本：

```powershell
python scripts/check_voice_setup.py
```

如果你当前在 `backend/` 目录，也可以运行：

```powershell
python ..\scripts\check_voice_setup.py
```

6. 重启 FastAPI 后端，然后访问：

```text
http://localhost:8000/api/voice/status
```

确认 `voiceEnabled=true`、`asrDependencyAvailable=true`、`modelPathExists=true`、`modelLooksValid=true`、`canRecord=true`。

7. 打开前端，点击“刷新语音状态”，勾选“语音输入”，点击“开始说话”，说一句例如“来一份黑椒牛肉饭”，再点击“停止说话”。

成功时页面应显示：

- 用户消息：ASR final transcript，例如“来一份黑椒牛肉饭”。
- Agent 回复：来自现有文本多 agent 订餐入口的回复。

如果 `TTS_ENABLED=true` 且 `pyttsx3` 可用，后端本机会播报 Agent 回复。`TTS_PLAYBACK_TARGET=server` 表示声音从运行 FastAPI 的机器播放；如果后端在 WSL、Docker、远程服务器，浏览器所在机器可能听不到声音。

### 没有语音播报声音怎么办

先区分三条链路：

1. 本机 `pyttsx3` 是否能发声。
2. FastAPI 的 TTS 队列是否能执行任务。
3. 语音订餐 WebSocket 的 `agent_reply` 是否触发了自动播报入队。

本机直测不需要启动 FastAPI：

```powershell
python scripts/test_tts.py --repeat 3 --gap 0.5 "这是一条语音播报测试。"
```

列出可用 voice，并按输出配置 `TTS_VOICE_NAME`：

```powershell
python scripts/test_tts.py --list-voices
```

例如：

```env
TTS_VOICE_NAME=Microsoft Huihui Desktop
```

`scripts/test_tts.py` 会直接 lazy import `pyttsx3`，打印 voice 数量、当前 voice、rate、volume，并执行 `engine.say()` 和 `engine.runAndWait()`。默认每条播报都会重新创建 pyttsx3 engine；如果需要对比复用 engine 是否导致“第一句后无声”，运行：

```powershell
python scripts/test_tts.py --repeat 3 --reuse-engine --gap 0.5 "这是一条语音播报测试。"
```

如果重建 engine 和复用 engine 两种模式都只有第一句有声，问题大概率不在订餐项目或 FastAPI TTS queue，而在系统音频、Windows SAPI、pyttsx3、默认输出设备、WSL/Docker/远程环境或远程桌面音频转发。

API 测试播报：

```powershell
curl.exe -X POST http://localhost:8000/api/voice/tts `
  -H "Content-Type: application/json" `
  -d "{\"text\":\"这是一条语音播报测试。\"}"
```

`queued=true` 只代表任务已进入后端 TTS 队列，不代表已经真实听到声音。连续测试 API 播报时，连续 POST 三次后应每 0.5 秒轮询一次状态，最多等 30 秒，直到 `jobsFinished` 增加 3、`queueSize=0` 且 `speaking=false`。继续查看：

```text
http://localhost:8000/api/voice/tts/status
```

关键字段：

- `queueInitialized`：TTS runner 是否已经懒初始化。
- `speaking`：当前是否正在执行播报任务。
- `queueSize` / `maxQueueSize`：队列长度和上限。
- `lastStartedAt` / `lastFinishedAt`：最近一次任务是否真的开始和结束。
- `lastSuccess`：最近一次 `runAndWait()` 是否成功结束。
- `lastError`：最近一次失败摘要，完整 traceback 只写后端日志。
- `jobsQueued` / `jobsStarted` / `jobsFinished`：累计入队、开始和完成任务数。
- `totalSuccesses` / `totalFailures`：累计成功和失败次数。
- `jobHistory`：最近 10 条任务摘要，只保存 job id、状态、时间、长度和短 preview，不保存完整文本。
- `currentVoice`：当前使用的 voice `{ id, name, languages }`。
- `maybeStuck`：如果 `speaking=true` 且超过 30 秒，会变为 true，通常表示 `pyttsx3` 或系统语音引擎卡住。
- `lastSource`：`manual` 表示 `/api/voice/tts` 测试播报，`auto` 表示语音订餐自动播报。

语音订餐自动播报使用后端自动触发方案：前端收到 WebSocket `agent_reply` 后只显示消息，不会再调用 `/api/voice/tts`，避免重复播报。自动播报是否入队以 WebSocket 的 `tts_status` 事件为准：

```json
{"type":"tts_status","utterance_id":"...","source":"auto","queued":true,"job_id":123,"playbackTarget":"server"}
```

`queued=true` 仍然只表示已加入后端本机播放队列；真实播放结果仍以 `GET /api/voice/tts/status` 的 `lastSuccess`、`lastError`、`lastFinishedAt` 为准。如果返回 `queued=false`，`reason` 会是稳定枚举，例如 `user_tts_preference_off`、`tts_disabled`、`can_speak_false`、`empty_text`、`tts_queue_full`、`tts_queue_stuck`、`duplicate_utterance`、`ignored_empty_transcript` 或 `tts_error`。

`TTS_PLAYBACK_TARGET=server` 的含义是声音从运行 FastAPI 后端的机器播放，不一定从浏览器所在机器播放。如果 FastAPI 运行在 WSL、Docker、远程服务器、无声卡环境、后台服务环境，或远程桌面没有转发音频，浏览器所在电脑可能听不到声音。

### 语音功能未开启排查

语音开关必须配置在后端 `.env`，不是前端 Vite `.env`。如果页面显示“后端语音未开启”，按下面顺序检查：

1. 在后端 `.env` 中设置：

```env
VOICE_ENABLED=true
ASR_ENGINE=vosk
VOSK_MODEL_PATH=./models/asr/vosk-cn
TTS_ENABLED=true
TTS_ENGINE=pyttsx3
TTS_PLAYBACK_TARGET=server
TTS_ENGINE_RECREATE_PER_TASK=true
```

2. 确认 `VOSK_MODEL_PATH` 指向解压后的真实 Vosk 中文模型目录。空目录只能说明路径存在，不能说明模型可用。
3. 重启 FastAPI 后端。`.env` 修改后，正在运行的 uvicorn 不会自动重新读取配置。
4. 访问 `GET http://localhost:8000/api/voice/status`，确认 `voiceEnabled=true` 且 `canRecord=true`。
5. 回到前端页面点击“刷新语音状态”，这只刷新语音控件，不会清空聊天记录或重置订单会话。

后端默认只尝试读取项目根目录 `.env`。如果需要指定其他文件，可以设置 `BACKEND_ENV_FILE=/absolute/path/to/.env`；相对路径会按后端进程工作目录解析。`BACKEND_ENV_FILE` 指向不存在文件时，status 的 `hints` 会显示实际尝试读取的路径，不会静默改读前端 `.env`。

`/api/voice/status` 的关键字段：

- `voiceEnabled`：后端 `VOICE_ENABLED` 是否为 true。
- `asrDependencyAvailable`：后端是否能找到 `vosk` 依赖。
- `modelPathExists`：`VOSK_MODEL_PATH` 路径是否存在。
- `modelLooksValid`：模型目录结构是否看起来像 Vosk 模型。这只是轻量启发式检查，不会加载模型权重；最终可用性仍以真实 Vosk lazy load 为准。
- `modelLoaded`：当前进程是否已经实际懒加载过 Vosk Model。
- `canRecord`：只有 `voiceEnabled && asrDependencyAvailable && modelPathExists && modelLooksValid` 全部满足时才为 true。
- `canSpeak`：只有 `voiceEnabled && ttsEnabled && ttsReady` 全部满足时才为 true。

三类常见状态：

- `VOICE_ENABLED=false`：前端显示“后端语音未开启”，开始说话按钮禁用，不会请求麦克风或建立 WebSocket。
- `VOICE_ENABLED=true` 但路径不存在：前端显示“ASR 模型路径不存在”，开始说话按钮禁用。
- `VOICE_ENABLED=true` 且路径存在但目录为空或结构不对：前端显示“ASR 模型目录结构无效”，开始说话按钮仍禁用。

如果 status 仍显示 `voiceEnabled=false`，检查：

- 后端运行目录是否正确。
- `.env` 是否在后端实际读取路径。
- 是否只修改了前端 Vite `.env`。
- 启动命令或系统环境变量是否覆盖了 `.env`。
- 是否已经重启 uvicorn/FastAPI。
- Docker、WSL、远程服务器是否正确传入环境变量。

## 故障排查 FAQ

### 前端显示无法获取语音状态怎么办？

先确认 FastAPI 后端已经启动，并且 `GET http://localhost:8000/api/voice/status` 能返回 JSON。检查前端 `VITE_API_BASE_URL`：默认可以不设置，前端会请求 `http://localhost:8000/api`；本地 dev 也可以设置 `VITE_API_BASE_URL=/api` 使用 Vite proxy。使用 proxy 时确认 `VITE_BACKEND_PROXY_TARGET` 指向正在运行的后端，例如 `http://localhost:8000`。

### TTS 状态成功但听不到声音怎么办？

当前是 server-side TTS。`TTS_PLAYBACK_TARGET=server` 表示声音从运行 FastAPI 的机器播放，不是从浏览器播放。检查系统输出设备、系统音量、Windows 应用静音、是否安装中文语音，以及 `GET /api/voice/tts/status` 的 `lastSuccess`、`lastError`、`maybeStuck` 和 `currentVoice`。

### 页面刷新后订单还在吗？

前端会把 `session_id` 保存在 `localStorage`，刷新页面会复用同一个会话，所以后端订单状态仍能接上。点击“重置”会生成新的 `session_id`，旧订单上下文不会继续影响新订单。

### `.env` 可以提交吗？

不可以。真实 `.env`、`.env.local` 和前端本地 env 文件都只留在本机。请提交 `.env.example`，并确保真实 API key 不进入 Git、README、测试或脚本。

### 如何确认项目没坏？

从项目根目录运行：

```powershell
.\scripts\check_all.ps1 -Build
```

它会运行后端 pytest、前端 Vitest、TypeScript 检查和前端 build。

## 扩展菜单

在 `backend/app/services/menu_service.py` 的 mock 菜单中添加 `MenuItem`，字段包括 `id`、`name`、`category`、`price`、`tags`、`spicy_level`、`available`、`options`、`aliases`、`description`。

新增菜品后建议补充：

- 菜名识别测试
- 价格/选项测试
- 推荐筛选测试

## 扩展 Agent

新增 agent 时保持三条规则：

1. 子 agent 只返回 action result 和 state patch。
2. 状态更新必须由 Orchestrator 校验后统一应用。
3. 修改语义路由或状态不变量时必须补 pytest。
