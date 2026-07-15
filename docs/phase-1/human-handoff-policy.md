# 阶段 1 人工接管政策

本文定义未来接管行为，不代表当前已有人工坐席、电话转接或回拨能力。

## 1. 接管原则

1. 顾客可随时要求真人；明确请求立即分类为 `HANDOFF`，不要求说明理由。
2. 对食品安全、身份/门店、价格、地址或商家状态不确定时，采取保守处理并接管。
3. 接管必须保留订单草稿、有效确认字段和未确认字段；不得把接管当作清空或提交。
4. “正在尝试连接人工”与“人工已经连接”必须分开。只有收到连接成功事件后才能宣称已连接。
5. 接管失败必须明确告知；不得沉默等待、伪造连接或自动提交订单。
6. 严重过敏、交叉污染、投诉、支付争议和系统安全事件不得通过无限追问拖延。
7. 摘要采用最少必要原则；不默认包含完整转写、原始音频、完整电话或完整地址。
8. 人工接管不扩大权限。人工只能访问被分配 restaurant/session 的必要资料。

## 2. 稳定原因代码

| 原因代码 | 触发条件 | 自动流程停止点 |
|---|---|---|
| `EXPLICIT_HUMAN_REQUEST` | 顾客明确要求真人 | 立即停止目标操作 |
| `SEVERE_ALLERGY` | 严重、可致命或反应程度不明的过敏声明 | 不继续自动点单或提交 |
| `CROSS_CONTAMINATION` | 要求核实制作流程或交叉污染 | 拒绝保证并请求人工/厨房核实 |
| `REPEATED_MISUNDERSTANDING` | 达到餐厅配置的连续纠正阈值 | 保留最后可确认草稿 |
| `AMBIGUOUS_ITEM` | 有多个菜品候选且有限澄清仍未解决 | 不选择候选 |
| `AMBIGUOUS_QUANTITY` | 数量仍可能对应多种解释 | 不修改数量 |
| `UNVERIFIED_ADDRESS` | 地址无法复述或配送范围无法核实 | 不提交配送订单 |
| `PRICE_UNAVAILABLE` | 权威价格不可用或冲突 | 不报猜测价格、不提交 |
| `MENU_DATA_MISSING` | 问题超出权威菜单或菜单数据缺失 | 不编造答案 |
| `COMPLAINT` | 顾客提出投诉或服务伤害主张 | 不自动裁决责任 |
| `REFUND_REQUEST` | 顾客要求退款 | 不自动退款 |
| `PAYMENT_DISPUTE` | 支付状态、扣款或金额争议 | 不索取完整卡号、不自动处理资金 |
| `MERCHANT_REJECTED` | 权威商家端明确拒单 | 不继续显示成功 |
| `MERCHANT_TIMEOUT` | 商家端超时且权威查询仍未知 | 不把 unknown 当 accepted |
| `SYSTEM_FAILURE` | 内部错误影响准确性或状态完整性 | 停止有副作用操作 |
| `LANGUAGE_UNSUPPORTED` | 经过有限澄清仍无法可靠理解语言 | 不猜测订单 |
| `ABUSE_OR_SECURITY` | 滥用、越权、注入或安全事件需要人工处置 | 拒绝危险目标并升级 |
| `REGULATED_ITEM` | 酒类、年龄受限等范围外商品 | 不处理该商品，必要时交餐厅 |

原因代码是审计分类，不是面向顾客的详细诊断，也不能包含个人资料。

## 3. 触发和有限澄清

- 无需澄清即接管：明确真人请求、严重过敏、投诉、退款、支付争议、商家明确拒单、关键系统状态损坏。
- 最多进行有限澄清后接管：模糊菜名、模糊数量、地址、价格缺失、语言不支持。具体最大轮数是 `ASM-006`/运营配置的一部分；未决定前测试采用“连续两次纠正后接管”的保守场景，不把它写成永久业务阈值。
- 目标操作为越权、伪造接受、绕过确认、保存完整银行卡或食品安全保证时，应先 `REFUSE` 该目标；如顾客仍需合法服务，再以新的 `HANDOFF` 决策接管。

## 4. 接管摘要契约

摘要只保存人工完成任务所需的结构化内容。示例全部为合成标识：

```json
{
  "session_id": "synthetic-session-0042",
  "restaurant_id": "simulation-restaurant",
  "branch_id": "simulation-branch-a",
  "locale": "yue-Hant-HK",
  "order_summary": [],
  "customer_confirmed_fields": [],
  "unconfirmed_fields": ["allergy_details"],
  "handoff_reason_code": "SEVERE_ALLERGY",
  "risk_notes": ["Do not guarantee allergen safety"],
  "last_user_messages": ["[synthetic redacted message]"],
  "forbidden_actions": ["submit_order", "guarantee_cross_contamination_free"]
}
```

字段要求：

- `session_id`、`restaurant_id`、`branch_id`：用于隔离和路由，必须来自当前上下文；
- `locale`：仅使用 `zh-CN`、`yue-Hant-HK`、`en-HK`、`mixed`；
- `order_summary`：结构化草稿，不含无关对话；
- `customer_confirmed_fields` / `unconfirmed_fields`：明确确认状态，防止人工误把候选当事实；
- `handoff_reason_code`：只能使用稳定原因代码；
- `risk_notes`：简短、可操作，不写医疗结论；
- `last_user_messages`：默认脱敏、数量受限，只有完成接管确有必要时包含；
- `forbidden_actions`：把尚不可执行的提交、保证、退款等动作传给人工界面。

不得把 API key、完整银行卡、无关历史、其他餐厅数据或未授权原始音频放入摘要。

## 5. 接管状态语义

推荐概念事件为 `handoff_requested`、`handoff_queued`、`human_connected`、`handoff_failed` 和 `handoff_completed`。这些是后续设计词汇，不是阶段 1 代码。

- `handoff_requested`/`handoff_queued`：只能说正在尝试或排队；
- `human_connected`：只有人工端明确接受并建立连接后才能宣称已连接；
- `handoff_failed`：必须带失败类型、草稿保留结果和可用下一步；
- 任一接管事件都不能隐式生成 `customer_confirmed`、`submission_started` 或 `merchant_accepted`。

## 6. 转人工失败政策

| 失败类型 | 顾客话术原则 | 订单保留状态 | 稍后回拨 | 禁止行为 |
|---|---|---|---|---|
| 无人工在线 | 明确“目前没有人工在线”，提供安全的稍后重试方式 | 保留未提交草稿并标记确认是否仍有效 | 仅在顾客明确同意、真实号码政策完成后允许 | 不声称已排到真人；不自动提交 |
| 转接超时 | 明确“连接超时，尚未接通” | 保留草稿；高风险字段保持未确认 | 同上 | 不把超时当拒单或接通 |
| 人工拒绝/无法受理 | 说明目前无法由人工处理并给出可用渠道 | 保留草稿；记录非个人化原因 | 需有餐厅政策和顾客授权 | 不公开内部人员信息；不自动裁决投诉/退款 |
| 连接中断 | 说明连接已中断，区分中断前是否已执行动作 | 以审计事件核实；未知状态不得猜测 | 可在授权后安排 | 不重复提交；不假定人工已经完成 |
| 系统故障 | 说明系统故障导致无法安全继续 | 冻结有副作用操作，保留可验证草稿快照 | 仅走独立、已验证渠道 | 不降级到无确认提交；不泄露堆栈/凭据 |

## 7. 接管验收

至少验证：明确真人请求召回率、严重过敏接管召回率、接管误触发率、摘要字段完整/最小化、转接失败无提交、跨餐厅隔离，以及 `human_connected` 不被提前宣称。对应指标见 `METRIC-002`、`METRIC-005`、`METRIC-006`、`METRIC-014` 和 `METRIC-015`。
