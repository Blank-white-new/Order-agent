# 阶段 1 追踪矩阵

本矩阵把产品要求、风险、控制、指标、机器可读场景和未来阶段连接起来。`SCENARIO-xxx` 对应 `evaluation/phase1_scenarios.jsonl` 的 `trace_id`。自动校验会阻止孤立要求、高严重度风险和阻塞指标。

## 1. 需求端到端追踪

| requirement | 产品要求摘要 | risks | control | metrics | scenarios | future_stage |
|---|---|---|---|---|---|---:|
| REQ-001 | Orchestrator 唯一裁决入口 | RISK-029,RISK-031 | 子 agent 只提议；状态和副作用 guard 集中校验 | METRIC-008,METRIC-011 | SCENARIO-027,SCENARIO-032 | 4 |
| REQ-002 | 香港仅为合成模拟市场 | RISK-025,RISK-026 | 固定 `HK_SIMULATION`；禁止真实顾客/餐厅/订单 | METRIC-004,METRIC-005 | SCENARIO-001,SCENARIO-137 | 2 |
| REQ-003 | 四个稳定 locale 标识 | RISK-015,RISK-017,RISK-020 | 分语言语料、独立报告、mixed 测试 | METRIC-013 | SCENARIO-015,SCENARIO-049,SCENARIO-083,SCENARIO-117 | 5 |
| REQ-004 | 角色最小权限与餐厅/会话隔离 | RISK-026,RISK-028,RISK-030,RISK-031 | 对象级授权、默认拒绝、访问审计 | METRIC-004,METRIC-005 | SCENARIO-028,SCENARIO-029 | 10 |
| REQ-005 | 自动操作只影响可逆草稿 | RISK-001,RISK-002,RISK-035 | mutation 白名单、状态 diff、无外部副作用 | METRIC-009,METRIC-010,METRIC-012 | SCENARIO-002,SCENARIO-003 | 4 |
| REQ-006 | 确认绑定复述、session 和版本 | RISK-001,RISK-002,RISK-007 | 候选复述、版本确认、问句不确认 | METRIC-002,METRIC-009,METRIC-010 | SCENARIO-007,SCENARIO-010,SCENARIO-011 | 4 |
| REQ-007 | 最终与重要字段必须确认 | RISK-002,RISK-004,RISK-010 | 字段确认清单、确认前不提交 | METRIC-010,METRIC-016 | SCENARIO-005,SCENARIO-006,SCENARIO-018 | 4 |
| REQ-008 | 顾客可随时要求真人 | RISK-038 | 明确请求直接 `HANDOFF` | METRIC-014,METRIC-015 | SCENARIO-022,SCENARIO-056 | 9 |
| REQ-009 | 严重过敏与交叉污染接管 | RISK-009,RISK-011,RISK-013,RISK-014 | 独立高敏字段、禁止保证、厨房/人工核实 | METRIC-006,METRIC-014 | SCENARIO-016,SCENARIO-017,SCENARIO-034 | 9 |
| REQ-010 | 持续歧义/故障/超范围接管 | RISK-001,RISK-002,RISK-003,RISK-039,RISK-045 | 有限澄清、fail closed、稳定原因代码 | METRIC-011,METRIC-014 | SCENARIO-009,SCENARIO-012,SCENARIO-025 | 9 |
| REQ-011 | 投诉、退款、争议和商家异常接管 | RISK-008,RISK-038,RISK-039,RISK-046 | 禁止自动裁决/退款；结构化人工摘要 | METRIC-014,METRIC-017,METRIC-029 | SCENARIO-019,SCENARIO-020,SCENARIO-021,SCENARIO-024 | 9 |
| REQ-012 | 绕过确认、伪造接受和滥用拒绝 | RISK-007,RISK-008,RISK-029,RISK-034 | 拒绝目标且不泄露规则；保留合法草稿 | METRIC-001,METRIC-007,METRIC-008 | SCENARIO-027,SCENARIO-031,SCENARIO-032 | 4 |
| REQ-013 | 他单/他店/后台越权拒绝 | RISK-026,RISK-028,RISK-030,RISK-031,RISK-036,RISK-037 | 对象授权、数据隔离、secret/日志保护 | METRIC-004,METRIC-005,METRIC-008 | SCENARIO-027,SCENARIO-028,SCENARIO-029 | 10 |
| REQ-014 | 拒绝食安保证和完整卡资料 | RISK-013,RISK-046 | 禁止绝对保证、卡数据模式阻断、可另行接管 | METRIC-005,METRIC-006,METRIC-008 | SCENARIO-017,SCENARIO-021,SCENARIO-033,SCENARIO-034 | 10 |
| REQ-015 | 未确认不得提交 | RISK-007 | 提交前验证当前 draft version 的确认 | METRIC-001,METRIC-002 | SCENARIO-007,SCENARIO-032 | 4 |
| REQ-016 | accepted 只来自权威明确结果 | RISK-008,RISK-033,RISK-039 | 验签、关联、显式状态语义 | METRIC-007,METRIC-017 | SCENARIO-023,SCENARIO-024,SCENARIO-032 | 8 |
| REQ-017 | 提交幂等且隔离 session/门店 | RISK-006,RISK-032,RISK-035,RISK-042 | 幂等键、nonce、锁、状态查询 | METRIC-003,METRIC-004,METRIC-005 | SCENARIO-026,SCENARIO-030 | 8 |
| REQ-018 | 重要变化使旧确认失效 | RISK-014 | draft version 变化、重新食安检查和确认 | METRIC-002,METRIC-012 | SCENARIO-008,SCENARIO-042 | 4 |
| REQ-019 | 默认合成且最少收集 | RISK-021,RISK-022,RISK-023,RISK-024,RISK-025 | 合成 fixture、目的限定、字段最小化 | METRIC-004,METRIC-005 | SCENARIO-026,SCENARIO-137 | 10 |
| REQ-020 | 数据分类和日志脱敏 | RISK-021,RISK-022,RISK-024,RISK-037,RISK-046 | 五级分类、结构化脱敏日志、禁止 key/卡数据 | METRIC-005,METRIC-008 | SCENARIO-006,SCENARIO-027,SCENARIO-033 | 10 |
| REQ-021 | 保留可配置、可审计、可删除 | RISK-023,RISK-027 | 期限配置、删除任务、处理者契约 | METRIC-005,METRIC-031 | SCENARIO-026,SCENARIO-128 | 10 |
| REQ-022 | 粤语不等同繁体普通话；切换不丢语义 | RISK-015,RISK-017,RISK-018,RISK-020 | 独立 locale、数字/实体和上下文金标 | METRIC-010,METRIC-013 | SCENARIO-015,SCENARIO-049,SCENARIO-083,SCENARIO-117 | 5 |
| REQ-023 | 菜单、价格、配送费来自权威服务 | RISK-003,RISK-012,RISK-040,RISK-041 | 版本化服务数据、缺失不猜测 | METRIC-009,METRIC-011 | SCENARIO-001,SCENARIO-004,SCENARIO-012,SCENARIO-013 | 3 |
| REQ-024 | 受限商品和明确非目标不进自动流程 | RISK-031,RISK-034,RISK-044 | 范围白名单、拒绝/接管、供应商禁用 | METRIC-014,METRIC-030 | SCENARIO-048,SCENARIO-137 | 7 |
| REQ-025 | 接管保留草稿和确认状态 | RISK-038 | 最少必要摘要、confirmed/unconfirmed 字段 | METRIC-014,METRIC-029 | SCENARIO-022,SCENARIO-056 | 9 |
| REQ-026 | 接管失败明确且不自动提交 | RISK-038,RISK-039,RISK-042,RISK-045 | 失败事件、保留草稿、禁止副作用 | METRIC-001,METRIC-014,METRIC-024,METRIC-025 | SCENARIO-009,SCENARIO-023,SCENARIO-025,SCENARIO-026 | 9 |
| REQ-027 | 决策可追踪到风险、指标和场景 | RISK-025,RISK-036 | 稳定 ID、矩阵和静态 validator | METRIC-008,METRIC-011 | SCENARIO-007,SCENARIO-027 | 11 |
| REQ-028 | 阶段 1 不调用真实 LLM | RISK-029,RISK-037 | offline guard、禁止 live CLI、网络桩 | METRIC-008 | SCENARIO-027,SCENARIO-061 | 2 |
| REQ-029 | 阶段 1 不收集真实资料/录音/订单/密钥 | RISK-021,RISK-023,RISK-025,RISK-037,RISK-046 | 合成数据、secret scan、无外部 provider | METRIC-005,METRIC-008 | SCENARIO-033,SCENARIO-137 | 2 |
| REQ-030 | 订单生命周期事件必须分离 | RISK-007,RISK-008,RISK-033 | 严格事件和话术映射、unknown 非 accepted | METRIC-011,METRIC-017 | SCENARIO-007,SCENARIO-023,SCENARIO-024 | 8 |

## 2. 必须接管规则覆盖

| handoff_reason_code | representative scenario |
|---|---|
| EXPLICIT_HUMAN_REQUEST | SCENARIO-022 |
| SEVERE_ALLERGY | SCENARIO-016 |
| CROSS_CONTAMINATION | SCENARIO-017 |
| REPEATED_MISUNDERSTANDING | SCENARIO-009 |
| AMBIGUOUS_ITEM | SCENARIO-044 |
| AMBIGUOUS_QUANTITY | SCENARIO-079 |
| UNVERIFIED_ADDRESS | SCENARIO-074 |
| PRICE_UNAVAILABLE | SCENARIO-012 |
| MENU_DATA_MISSING | SCENARIO-081 |
| COMPLAINT | SCENARIO-019 |
| REFUND_REQUEST | SCENARIO-020 |
| PAYMENT_DISPUTE | SCENARIO-021 |
| MERCHANT_REJECTED | SCENARIO-024 |
| MERCHANT_TIMEOUT | SCENARIO-023 |
| SYSTEM_FAILURE | SCENARIO-025 |
| LANGUAGE_UNSUPPORTED | SCENARIO-049 |
| ABUSE_OR_SECURITY | SCENARIO-132 |
| REGULATED_ITEM | SCENARIO-048 |

## 3. 必须拒绝规则覆盖

| refusal rule | representative scenario |
|---|---|
| prompt injection / 内部提示与密钥 | SCENARIO-027 |
| 其他餐厅/后台越权 | SCENARIO-028 |
| 查看其他顾客订单 | SCENARIO-029 |
| 恶意重复请求 | SCENARIO-030 |
| 骚扰、滥用和日志注入 | SCENARIO-031 |
| 绕过确认或伪造商家接受 | SCENARIO-032 |
| 保存完整银行卡资料 | SCENARIO-033 |
| 保证无法核实的食品安全信息 | SCENARIO-034 |
| 发送真实短信 | SCENARIO-137 |

## 4. 阻塞指标覆盖

| blocking metric | representative scenario |
|---|---|
| METRIC-001 错误自动提交 | SCENARIO-007,SCENARIO-032 |
| METRIC-002 确认绕过 | SCENARIO-007,SCENARIO-026 |
| METRIC-003 重复外部订单 | SCENARIO-030 |
| METRIC-004 跨会话污染 | SCENARIO-028,SCENARIO-029 |
| METRIC-005 跨餐厅数据泄露 | SCENARIO-028 |
| METRIC-006 严重过敏遗漏 | SCENARIO-016,SCENARIO-017 |
| METRIC-007 伪造商家接受 | SCENARIO-023,SCENARIO-024,SCENARIO-032 |
| METRIC-008 真实 LLM 意外调用 | SCENARIO-027 |

## 5. 静态覆盖结论

- 需求：30，关联场景：30，孤立：0。
- 风险：46（`HIGH` 23、`CRITICAL` 19、`MEDIUM` 4）；高严重度 42，孤立：0。
- 指标：31，关联场景：31；阻塞指标 8，孤立：0。
- 场景：140；每条至少关联一个需求、风险或指标，实际全部具有三类引用。
- 接管原因代码：18，均有场景；拒绝规则均有场景。

这些是目录和规范的静态覆盖结论，不代表对应未来控制已经实现或通过生产验证。运行 `python scripts/validate_phase1_scenarios.py` 重新计算机器可读覆盖。
