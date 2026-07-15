# 当前能力与稳定基线

本文描述阶段 0 冻结时已经存在并经过验证的能力。它是本机演示基线，不是生产系统承诺。

## 当前已支持

- 文本多轮订餐：会话状态由 Orchestrator 统一路由、校验和更新。
- 菜单与推荐：菜品、价格、推荐候选和配送费来自服务层及校验后的菜单配置。
- 订单修改：添加、删除、换菜、数量修改，以及辣度、忌口和备注等定制。
- 配送与自取：支持履约方式选择、地址和电话收集；电话在前端掩码展示。
- 顾客确认：下单前必须确认；提交后旧订单锁定。当前提交只产生内存中的 mock order。
- 本机中文 ASR：可选 Vosk 中文模型，浏览器音频经 WebSocket 发送到后端。
- 本机 TTS：Windows 上可选 server-side `pyttsx3`；声音从运行 FastAPI 的机器播放。
- WebSocket 语音演示：final transcript 进入与文本相同的 Orchestrator，语音网关不直接修改订单。
- LLM fallback sandbox：支持 `disabled`、`fake`、`replay`、`shadow`；规则始终优先，live 默认且在阶段 0 中强制禁用。
- 自动测试与 V3 评估：后端 pytest、前端 Vitest/TypeScript/build 以及 57 条离线对话评估。
- Windows 启动脚本：提供文本开发启动入口，以及准备好 `.env` 和 Vosk 模型后的本机语音一键启动/停止入口。

## 当前明确不支持

- 真实电话呼入、SIP 或 PSTN。
- 普通话、粤语、英语三语生产能力。
- 真实 POS、实时库存或商家后台。
- 数据库持久化或多租户。
- 支付、真实订单或真实配送。
- 真人接管或真实顾客服务。
- 生产部署、香港试点或欧洲部署。
- 欧洲合规或 GDPR 合规声明。

## 阶段 0 测试基线

阶段 0 的可执行代码与基础设施基线为 commit `dda08aaf98121f6c53448eb8785c5137df0de4c6`。文档提交不改变订餐业务行为。验证日期为 2026-07-15，环境为 Windows 11 `10.0.22621`、Python 3.13.2、Node.js 24.15.0、npm 11.12.1。

| 检查 | 本轮结果 |
|---|---|
| `scripts/check_all.ps1 -Build` | 通过 |
| GitHub Actions | [run 29416536835](https://github.com/Blank-white-new/Order-agent/actions/runs/29416536835) 通过（Windows，2m46s） |
| pytest | 830 passed，3 warnings |
| Vitest | 7 files passed，69 tests passed |
| TypeScript | `tsc --noEmit` 通过 |
| Vite build | 通过，39 modules transformed |
| V3 对话评估 | 57/57，100% |
| false mutation | 0 |
| confirmation bypass | 0 |
| live LLM trigger | 0 |
| `npm audit` | 0 vulnerabilities |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| `pip check` | 无依赖冲突 |
| `pip-audit` | No known vulnerabilities found |
| 全新锁环境 | 安装、pytest、V3 全部通过 |
| 本机文本 API smoke | health、11 项菜单、reset、chat 通过 |

上述结果的含义必须分开理解：

- 自动测试通过：规则路由、状态不变量、API、前端组件、类型和构建在离线配置下通过。
- 本机接口通过：阶段 0 以不存在的临时 env 文件、关闭 LLM/语音/TTS 的方式启动 FastAPI，并完成文本 API smoke。
- 仍需真人硬件听感：本轮没有把麦克风识别准确率、扬声器音量、回声、barge-in 或中文 TTS 听感计为已验收。
- 尚未完成生产验证：没有真实电话、真实商户、真实顾客、支付、持久化、容量、容灾、安全合规或生产部署验证。

## 运行安全边界

CI 和标准检查固定使用：

```text
LLM_FALLBACK_MODE=disabled
LLM_FALLBACK_ENABLED=false
ALLOW_LIVE_LLM=false
VOICE_ENABLED=false
TTS_ENABLED=false
```

这些检查不读取本机 `.env`，不下载或加载 Vosk 模型，不请求麦克风或扬声器，也不需要 API key。语音能力是否真实可用，仍应按 [语音演示与排障](voice-troubleshooting.md) 在目标 Windows 机器上人工验收。
