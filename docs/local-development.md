# 本地开发与干净环境安装

本文是阶段 0 的从零复现入口。命令默认在仓库根目录、Windows PowerShell 中执行。

## 已验证平台和版本

阶段 0 只正式验证 Windows 11 和 GitHub Actions `windows-latest`。纯文本代码可能在其他系统运行，但本阶段不声明 Linux/macOS 支持，也不声明 Linux/macOS 语音支持。

| 工具 | 推荐及 CI 版本 | 声明范围 |
|---|---|---|
| Python | 3.13.2 | 阶段 0 只验证并支持此精确版本 |
| pip | 26.1.2 | 生产环境与维护工具环境均显式固定 |
| pip-tools | 7.5.3 | 仅用于生成依赖锁文件 |
| pip-audit | 2.10.1 | 仅用于依赖漏洞审计 |
| Node.js | 24.15.0 | `>=24 <25`，只实测 24.15.0 |
| npm | 11.12.1 | `>=11 <12`，只实测 11.12.1 |

根目录 `.python-version` 和 `.nvmrc` 保存精确版本；`frontend/package.json` 的 `engines` 保存范围，`packageManager` 固定 npm 11.12.1。

## 从全新克隆安装

```powershell
git clone https://github.com/Blank-white-new/Order-agent.git
cd Order-agent

python --version
node --version
npm --version

python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install "pip==26.1.2"
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
.\backend\.venv\Scripts\python.exe -m pip check

Push-Location frontend
npm ci
Pop-Location
```

`backend/requirements.txt` 只描述生产直接依赖；日常安装和 CI 必须使用带精确版本与哈希的 `backend/requirements.lock.txt`。运行应用或执行测试不需要安装开发工具。

`backend/requirements-dev.in` 只列出固定的 pip、pip-tools 和 pip-audit；`backend/requirements-dev.lock.txt` 则锁定这些维护/审计工具的完整传递依赖与哈希。开发工具不得加入生产 `requirements.txt` 或生产虚拟环境。

## `.env` 与配置分层

纯文本模式、自动测试和 V3 不需要 `.env`。需要本机自定义配置时才复制安全模板：

```powershell
Copy-Item .env.example .env
notepad .env
```

不要提交 `.env`，不要把真实 key 写入脚本、README、测试或 workflow。配置分层约定如下：

- development：本机 `.env`，仅保存开发者本机设置。
- test/CI：使用进程环境变量，强制关闭 live LLM、语音和 TTS，不创建 `.env.test`。
- staging/production：阶段 0 不提供实际环境文件；未来应由部署平台的 Secret Manager 注入，不能提交 `.env.staging` 或 `.env.production`。
- `.env.example`：唯一可提交的安全示例，不包含真实凭据。

## 纯文本模式

后端窗口：

```powershell
$env:LLM_FALLBACK_MODE="disabled"
$env:LLM_FALLBACK_ENABLED="false"
$env:ALLOW_LIVE_LLM="false"
$env:VOICE_ENABLED="false"
$env:TTS_ENABLED="false"

Push-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端窗口：

```powershell
Push-Location frontend
npm run dev
```

打开 `http://127.0.0.1:3000/`。默认 API 地址为 `http://localhost:8000/api`。如果需要 Vite 同源代理：

```powershell
$env:VITE_API_BASE_URL="/api"
$env:VITE_BACKEND_PROXY_TARGET="http://127.0.0.1:8000"
npm run dev
```

已按锁文件安装后，也可运行文本开发快捷入口：

```powershell
.\scripts\start-dev.ps1
```

它会打开两个开发终端；用各窗口的 `Ctrl+C` 停止。

## 可选本机语音模式

语音是 Windows 本机演示能力。先下载 Vosk 中文模型，例如 `vosk-model-small-cn-0.22`，解压后的模型根目录应直接包含 `am/`、`conf/` 和 `graph/`：

```text
models/asr/vosk-cn/
```

模型、音频和日志都被 Git 忽略，不得提交。然后在本机 `.env` 设置：

```env
VOICE_ENABLED=true
ASR_ENGINE=vosk
VOSK_MODEL_PATH=./models/asr/vosk-cn
TTS_ENABLED=true
TTS_ENGINE=pyttsx3
TTS_PLAYBACK_TARGET=server
```

检查配置并一键启动/停止：

```powershell
.\backend\.venv\Scripts\python.exe scripts\check_voice_setup.py
.\scripts\start_order_system.ps1
.\scripts\stop_order_system.ps1
```

该启动器要求 `.env`、完整 Vosk 模型和可用端口；server-side TTS 从运行 FastAPI 的机器播放。自动测试不验证真实麦克风、扬声器或听感。

## 质量检查与 V3

完整本地检查：

```powershell
.\scripts\check_all.ps1 -Build
```

脚本会暂存、强制并恢复安全环境变量，不读取 provider 凭据，也不触发语音硬件。V3 回归：

```powershell
.\backend\.venv\Scripts\python.exe -B evaluation\run_dialogue_eval_v3.py `
  --dataset evaluation\dialogues_v3.jsonl `
  --fail-on-regression
```

依赖审计：

```powershell
$env:PYTHONUTF8="1"
python -m venv .tooling-venv
.\.tooling-venv\Scripts\python.exe -m pip install "pip==26.1.2"
.\.tooling-venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock.txt
.\.tooling-venv\Scripts\python.exe -m pip check
.\.tooling-venv\Scripts\python.exe -m pip_audit -r backend\requirements.lock.txt

Push-Location frontend
npm audit
npm audit --audit-level=high
Pop-Location
```

## 重新生成后端锁文件

只能在 Python 3.13.2 环境中生成。脚本固定使用 pip 26.1.2，并在用户的 LocalAppData 临时目录创建隔离 tooling venv；正常维护从 `requirements-dev.lock.txt` 安装 pip-tools 7.5.3。只重新生成生产锁：

```powershell
.\scripts\compile_backend_lock.ps1
```

修改 `requirements-dev.in` 后，同时刷新开发工具锁和生产锁：

```powershell
.\scripts\compile_backend_lock.ps1 -RefreshDevLock -Verify
```

只有开发工具锁不存在或已损坏时，才使用脚本内记录的固定 bootstrap pip-tools 7.5.3：

```powershell
.\scripts\compile_backend_lock.ps1 -RefreshDevLock -BootstrapDevLock -Verify
```

脚本使用 `pip-compile --generate-hashes --allow-unsafe`，使 pip 与 setuptools 也拥有精确版本和哈希；它保留平台 marker，并拒绝本机绝对路径、`file:///`、私有索引、直接 URL 和 editable 安装。`-Verify` 会在仓库外新虚拟环境安装生产锁并执行 `pip check`，临时环境随后自动清理。

锁文件变化后必须检查 `git diff`，再次运行脚本确认无无意义 diff，并重新执行全量测试、V3、`pip-audit` 和 npm audit。生产直接依赖输入 `requirements.txt` 不应因工具链维护而变化。

## CI 与本地命令对应关系

| GitHub Actions 步骤 | 本地对应命令 |
|---|---|
| 后端锁安装和依赖一致性 | `pip install -r backend/requirements.lock.txt`、`pip check` |
| 维护工具锁安装 | `.tooling-venv` 安装固定 pip 和 `requirements-dev.lock.txt` |
| 前端锁安装 | `cd frontend; npm ci` |
| 全量测试、类型和构建 | `scripts/check_all.ps1 -Build` |
| 对话回归 | V3 命令并加 `--fail-on-regression` |
| Python 安全扫描 | `python -m pip_audit -r backend/requirements.lock.txt` |
| npm 高危门槛 | `npm audit --audit-level=high` |

CI 不需要 `.env`、Vosk 模型、麦克风、扬声器、桌面快捷方式、真实 key 或电话平台。

CI 中 `actions/checkout`、`actions/setup-python` 和 `actions/setup-node` 均使用官方仓库的完整 40 位 commit SHA，行尾注释保留对应 major 版本。Dependabot 的 `github-actions` 更新器仍会提出 SHA 更新 PR；所有更新必须经过同一工作流，不能直接信任或自动合并。

## 常见问题

### PowerShell 不允许运行脚本

只为当前 PowerShell 进程临时放行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

不要为了本项目永久降低整机执行策略。

### 中文路径与编码

阶段 0 已在包含中文用户名的路径中完成测试。`pip-audit` 的某些传递工具在旧 Windows 控制台编码下可能解码失败，运行前设置：

```powershell
$env:PYTHONUTF8="1"
```

若其他第三方工具仍不能处理中文或空格路径，可克隆到纯 ASCII 路径；项目命令本身不得依赖本机绝对路径。

### `npm ci` 报 `EPERM` 且锁住 `esbuild.exe`

先停止正在使用同一 `node_modules` 的 Vite 服务：

```powershell
.\scripts\stop_order_system.ps1
```

如果服务由 `start-dev.ps1` 启动，在对应终端按 `Ctrl+C`，确认 Node/esbuild 已退出后重试 `npm ci`。

### 没有 `.env` 或 Vosk 模型时测试能否运行

可以。标准测试与 CI 强制文本离线模式。只有本机语音演示需要 `.env`、Vosk 模型和音频硬件。

### TTS 显示成功但没有声音

`TTS_PLAYBACK_TARGET=server` 表示声音从后端机器播放。检查 Windows 输出设备、音量、中文语音包和 `GET /api/voice/tts/status`；状态成功不等于真人已经听到声音。
