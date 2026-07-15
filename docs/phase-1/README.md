# 阶段 1：产品范围、风险边界和验收指标

阶段 1 已把后续阶段需要遵守的产品、安全、数据、人工接管和订单成功语义固化为文档与 140 条合成机器可读场景。本阶段没有实现数据库、多租户、三语解析、电话/POS/支付、后台或生产订单代码，也没有改变当前订餐业务行为。

## 文档索引

- [统一术语](terminology.md)
- [产品范围和角色边界](product-scope.md)
- [订单成功定义](order-success-definition.md)
- [人工接管政策](human-handoff-policy.md)
- [风险登记册](risk-register.md)
- [数据政策](data-policy.md)
- [验收指标](acceptance-metrics.md)
- [官方研究来源](research-sources.md)
- [产品决策归档](product-decisions.md)
- [需求—风险—指标—场景追踪矩阵](traceability-matrix.md)
- [机器可读场景](../../evaluation/phase1_scenarios.jsonl)及其 [Schema](../../evaluation/phase1_scenarios.schema.json)

## 决策摘要

- 统一处理模型只有 `AUTO_DRAFT`、`CONFIRM`、`HANDOFF`、`REFUSE`；不存在自动提交、自动付款、自动退款或自动保证过敏安全。
- 顾客确认、发送到餐厅、餐厅接受和履约完成是不同事件。只有权威商家明确接受才能称为“餐厅已接受”。当前 `MOCK-ORDER-0001` 不是商家接受。
- 严重过敏、交叉污染核实、投诉、退款、支付争议、持续歧义、商家异常和系统故障必须进入人工边界；越权、伪造接受、绕过确认、完整卡资料和无法核实的安全保证必须拒绝目标操作。
- 数据默认合成、目的限定和最少收集；原始音频默认不持久化，日志不得记录完整电话、地址、转写、过敏详情或密钥。具体真实保留期限留待适用法律和运营审查。

## 香港模拟和三语方向

`HK_SIMULATION` 只代表模拟市场：没有真实香港顾客、餐厅、地址、电话号码、付款或订单，也不代表香港试点开始。初始对象只限单门店或少量门店的普通外卖/自取业务。结果不能自动证明欧洲要求，欧洲阶段须按具体国家重新适配。

未来语言方向标识为 `zh-CN`、`yue-Hant-HK`、`en-HK` 和 `mixed`。粤语按独立语言能力设计，不等同“繁体普通话”；阶段 1 只定义边界和场景，不实现三语解析或语音 provider。

## 核心非目标

真实支付/退款、实时库存、商家或坐席后台、真实 POS、CRM/营销、真实电话/短信、受限商品、跨餐厅订单、欧洲多国部署、多租户和无人工兜底的完全自动化均不在本阶段。

## 场景与覆盖

| 维度 | 数量 |
|---|---:|
| 总场景 | 140 |
| `zh-CN` | 35 |
| `yue-Hant-HK` | 35 |
| `en-HK` | 35 |
| `mixed` | 35 |
| `AUTO_DRAFT` | 16 |
| `CONFIRM` | 31 |
| `HANDOFF` | 58 |
| `REFUSE` | 35 |
| 需求 / 风险 / 指标 | 30 / 46 / 31 |
| 高严重度风险孤立项 / 阻塞指标孤立项 | 0 / 0 |

校验不调用生产 Agent 或真实 LLM：

```powershell
.\backend\.venv\Scripts\python.exe scripts\validate_phase1_scenarios.py
.\scripts\check_all.ps1 -Build
```

## 产品决策状态

阶段 1 的五项产品决定已在[产品决策归档](product-decisions.md)中明确负责人和状态：

- `DEC-001` 人工服务时间和回拨：`DEFERRED_CONFIGURABLE`；
- `DEC-002` 大幅修改和复杂团体订单：`RESTAURANT_CONFIGURABLE`；
- `DEC-003` 商家接受和幂等：`APPROVED_FOR_DOMAIN_MODEL`；
- `DEC-004` 过敏原权威来源：`RESTAURANT_DECLARED_ONLY`；
- `DEC-005` 真实数据保留和合规：`DEFERRED_UNTIL_REAL_PILOT`。

这些状态允许阶段 2 建立明确的数据模型，不关闭风险、不启用真实外部系统，也不替代后续餐厅、运营、食品安全或法律审查。

## 进入阶段 2 的闸门

进入阶段 2 前必须保持：本目录文档（含产品决策归档）审阅通过；140 条场景和 Schema 校验通过；原 pytest/Vitest/TypeScript/build 与 V3 无回归；false mutation、confirmation bypass、live LLM trigger 和八项阻塞计数为 0；高严重度风险、接管/拒绝规则与阻塞指标无孤立项；阶段 1 PR 最新 CI 通过并按分支保护要求合并；没有把本规范误实现为阶段 2 生产能力。
