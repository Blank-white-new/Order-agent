# Public Demo Readiness

本清单用于公开演示或发布前最后复核。它只覆盖当前静态 demo 能力，不代表生产商用系统。

## 发布前检查清单

- 当前分支基于最新 `main`。
- `git status --short` 为空，且没有跟踪 `.env`、虚拟环境、`node_modules`、构建产物、本机日志或临时录屏原文件。
- `LLM_FALLBACK_MODE=disabled`，`LLM_FALLBACK_ENABLED=false`，`ALLOW_LIVE_LLM=false`。
- 没有真实 API key、真实 token、真实密码、私人截图、真实手机号或真实地址进入 Git。
- 文本 demo 使用示例手机号 `13800000000`，并确认前端展示为掩码。
- 菜单、价格、配送费来自服务层和菜单配置，不在演示中声称真实商家库存或真实交易。
- 公开说明中不写“生产可用”“真实支付”“真实商家后台”“库存已支持”或“live LLM 默认开启”。

## 本机启动检查

后端：

```powershell
cd .\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd .\frontend
npm run dev
```

打开：

```text
http://127.0.0.1:3000/
```

必须确认：

- `GET http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}`。
- 页面能加载菜单、聊天区、订单摘要和语音控件。
- 浏览器 console 无阻断性 error。
- 后端日志没有真实 LLM 调用。
- `/api/menu` 返回 11 个配置化菜单项。

## 文本 Demo 检查

流程 A，推荐点餐：

1. `推荐一下`
2. `第一个来一份`
3. `再来一份可乐`
4. `把可乐删掉`
5. `查看订单`

期望：推荐出现，第一项加入订单，可乐可加入并删除，订单摘要只保留已点菜品。

流程 B，定制和配送：

1. `鸡腿饭少辣，不要香菜，米饭多一点`
2. `我要配送到中山大学南校园，电话是 13800000000`
3. `确认订单`

期望：辣度、忌口、备注展示正确；地址进入订单状态；电话展示为掩码；提交后显示 mock order。

流程 C，提交后锁定：

1. 在已提交订单后输入 `鸡腿饭改成两份`

期望：系统提示订单已提交，不能继续修改旧订单，右侧订单不变。

## 菜单配置 Smoke

- `GET /api/menu` 返回 11 个菜单项。
- `鸡腿饭`、`宫保鸡丁饭`、`黑椒牛肉饭`、`可乐` 存在。
- 输入 `机腿饭来一份` 能匹配到 `鸡腿饭`。
- `鸡腿饭少辣` 能写入辣度。
- `鸡腿饭不要香菜` 能写入忌口。
- 修改 `backend/app/data/menu.json` 后需要重启后端才会生效。
- 如设置 `MENU_CONFIG_PATH`，外部配置加载失败应直接报错，不应静默回退到内置菜单。

## 安全和隐私检查

运行检查：

```powershell
.\backend\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
.\scripts\check_all.ps1 -Build
.\backend\.venv\Scripts\python.exe -B evaluation\run_dialogue_eval_v3.py --dataset evaluation\dialogues_v3.jsonl
```

再做关键词搜索：

- `DEEPSEEK_API_KEY`
- `LLM_FALLBACK_API_KEY`
- `sk-`
- `Authorization`
- `Bearer`
- `password`
- `token`
- `secret`
- `MENU_CONFIG_PATH`
- `13800000000`

允许 `.env.example`、README、测试或演示文档出现占位符和示例手机号；不得出现真实凭据或私人路径。

## 已知限制

- 当前是公开 demo，不是生产商用系统。
- 订单提交是 mock order，不会产生真实交易。
- 没有真实支付、库存、商家后台、数据库菜单管理或热更新。
- 外部菜单配置修改后需要重启后端。
- 语音真实链路依赖本机 Vosk 模型、麦克风权限、浏览器权限和本机 TTS 环境。
- live LLM 未启用；如需开启，需要单独安全评审和凭据管理流程。

## 推荐录屏流程

1. 启动后端和前端。
2. 打开 `http://127.0.0.1:3000/`。
3. 点击“新订单”。
4. 录制流程 A 和流程 B。
5. 提交后补录一次流程 C，展示生命周期锁定。
6. 保持调试信息默认折叠，避免展示终端、`.env` 或本机私人路径。
