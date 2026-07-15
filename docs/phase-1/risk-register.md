# 阶段 1 风险登记册

本登记册覆盖香港模拟订餐方向的产品、食品安全、语言、数据、安全和运营风险。它不是法律、医疗或生产认证。`likelihood` 使用 `UNLIKELY/POSSIBLE/LIKELY`，`severity` 使用 `MEDIUM/HIGH/CRITICAL`，`detectability` 使用 `EASY/MODERATE/HARD`；综合 `risk_level` 为 `R2/R3/R4`，其中 `R4` 最高。所有条目在对应后续阶段完成实现和实测前保持 `OPEN`。

## 1. 风险识别与分级

| risk_id | name | description | cause | impact | likelihood | severity | detectability | risk_level | owner_role | future_stage | status |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| RISK-001 | 错菜 | 草稿或提交项与顾客意图不同 | 模糊菜名、别名冲突、错误引用 | 错单、投诉、食安影响 | POSSIBLE | HIGH | MODERATE | R3 | 对话负责人 | 4 | OPEN |
| RISK-002 | 错数量 | 数量、单位或增减方向错误 | 数字识别、上下文或重复请求错误 | 多收费、浪费或缺单 | POSSIBLE | HIGH | MODERATE | R3 | 对话负责人 | 4 | OPEN |
| RISK-003 | 错价格 | 报价或总价不是权威当前价格 | 缓存过期、推断或服务缺失 | 争议、误导、损失 | POSSIBLE | HIGH | MODERATE | R3 | 菜单负责人 | 3 | OPEN |
| RISK-004 | 错地址 | 未确认或音近地址被采用 | ASR、归一化或候选误用 | 配送失败、资料泄露 | POSSIBLE | HIGH | MODERATE | R3 | 履约负责人 | 4 | OPEN |
| RISK-005 | 错门店 | 订单绑定错误 branch | 门店上下文丢失或默认值错误 | 错餐厅收单、数据越界 | UNLIKELY | CRITICAL | HARD | R4 | 平台负责人 | 2 | OPEN |
| RISK-006 | 重复订单 | 一个确认产生多个外部订单 | 重试、超时、并发或重放 | 重复制作/扣费 | POSSIBLE | CRITICAL | MODERATE | R4 | 商家集成负责人 | 8 | OPEN |
| RISK-007 | 未确认下单 | 无有效最终确认即提交 | 确认词误判、旧确认复用 | 非授权订单 | UNLIKELY | CRITICAL | MODERATE | R4 | 产品安全负责人 | 4 | OPEN |
| RISK-008 | 未接受却宣称成功 | pending/unknown/本地 ID 被当 accepted | 状态混淆或乐观话术 | 顾客误信、漏单 | POSSIBLE | CRITICAL | HARD | R4 | 商家集成负责人 | 8 | OPEN |
| RISK-009 | 过敏信息遗漏 | 严重过敏未进入安全流程 | 识别失败或字段丢失 | 严重人身伤害 | POSSIBLE | CRITICAL | HARD | R4 | 食品安全负责人 | 4 | OPEN |
| RISK-010 | 忌口被当过敏 | 普通偏好被升级为医学过敏 | 术语混用或过度推断 | 不必要接管、信息失真 | POSSIBLE | MEDIUM | MODERATE | R2 | 食品安全负责人 | 4 | OPEN |
| RISK-011 | 过敏被当普通备注 | allergy 降级为普通 exclusion/note | 分类或字段映射错误 | 安全控制失效 | POSSIBLE | CRITICAL | HARD | R4 | 食品安全负责人 | 4 | OPEN |
| RISK-012 | 虚构配料信息 | agent 回答无权威来源的配料/过敏原 | 菜单缺失、生成式猜测 | 错误食品安全决定 | POSSIBLE | CRITICAL | HARD | R4 | 菜单负责人 | 3 | OPEN |
| RISK-013 | 错误保证无交叉污染 | 系统对制作环境作绝对保证 | 缺少厨房核实或话术错误 | 严重人身伤害 | POSSIBLE | CRITICAL | EASY | R4 | 食品安全负责人 | 9 | OPEN |
| RISK-014 | 换菜后未重检过敏 | 订单变化仍沿用旧安全判断 | 确认/风险状态未失效 | 新菜引入过敏原 | POSSIBLE | CRITICAL | HARD | R4 | 食品安全负责人 | 4 | OPEN |
| RISK-015 | 普通话粤语混淆 | 语言或同音词被错误解释 | 方言模型/路由不足 | 错菜、错数量或失去信任 | POSSIBLE | HIGH | MODERATE | R3 | 语言负责人 | 5 | OPEN |
| RISK-016 | 繁简菜名重复 | 同一/不同菜品别名冲突 | 数据规范和消歧不足 | 错菜或重复展示 | POSSIBLE | HIGH | EASY | R3 | 菜单负责人 | 3 | OPEN |
| RISK-017 | 中英混合解析错误 | mixed 输入丢失修饰词或目标 | 代码切换、分词或实体合并错误 | 错单、漏备注 | LIKELY | HIGH | MODERATE | R3 | 语言负责人 | 5 | OPEN |
| RISK-018 | 数字价格数量混淆 | 数字被分配给错误字段 | 语序、币种、量词或 ASR 错误 | 错数量/错价 | POSSIBLE | HIGH | MODERATE | R3 | 对话负责人 | 5 | OPEN |
| RISK-019 | 地址音近词 | 地址被菜名或其他同音词替换 | ASR 和领域词冲突 | 错配送、资料误存 | POSSIBLE | HIGH | HARD | R3 | 履约负责人 | 6 | OPEN |
| RISK-020 | 切换语言后上下文丢失 | locale 变化重置或错绑上下文 | 会话/语言状态设计不足 | 订单污染或重复询问 | POSSIBLE | HIGH | MODERATE | R3 | 语言负责人 | 5 | OPEN |
| RISK-021 | 电话泄露 | 完整号码出现在 UI、日志或摘要 | 无掩码、调试输出或越权 | 隐私伤害、骚扰 | POSSIBLE | HIGH | MODERATE | R3 | 隐私负责人 | 10 | OPEN |
| RISK-022 | 地址泄露 | 完整地址被无关人员或系统获取 | 日志、摘要或跨会话访问 | 隐私和人身安全风险 | POSSIBLE | HIGH | MODERATE | R3 | 隐私负责人 | 10 | OPEN |
| RISK-023 | 录音长期保存 | raw audio 无期限或超目的保留 | 默认持久化、缺少删除配置 | 高敏资料暴露 | POSSIBLE | HIGH | HARD | R3 | 隐私负责人 | 10 | OPEN |
| RISK-024 | 转写进入日志 | 完整 transcript 被普通日志采集 | 便捷调试、异常打印 | 大规模个人资料泄露 | LIKELY | HIGH | MODERATE | R3 | 平台负责人 | 10 | OPEN |
| RISK-025 | 测试数据混入生产 | fixture/合成身份进入真实流程或反向混入 | 环境隔离和标识不足 | 错单、泄露、指标污染 | UNLIKELY | CRITICAL | HARD | R4 | 测试负责人 | 10 | OPEN |
| RISK-026 | 跨餐厅数据泄露 | 一个餐厅可访问另一餐厅数据 | 授权/租户隔离缺陷 | 严重隐私和商业损害 | UNLIKELY | CRITICAL | HARD | R4 | 安全负责人 | 10 | OPEN |
| RISK-027 | 数据无法删除 | 无法定位或清理处理者副本 | 缺少索引、期限和删除工作流 | 超期保留、权利请求失败 | POSSIBLE | HIGH | HARD | R3 | 隐私负责人 | 10 | OPEN |
| RISK-028 | 未授权访问 | 人员/服务读取超权限资料 | 身份、角色或密钥控制失败 | 数据泄露和越权操作 | POSSIBLE | CRITICAL | HARD | R4 | 安全负责人 | 10 | OPEN |
| RISK-029 | Prompt injection | 顾客文本尝试覆盖规则或获取内部信息 | 未隔离指令/数据或 LLM 误信 | 越权、泄露、状态破坏 | LIKELY | HIGH | MODERATE | R3 | 安全负责人 | 4 | OPEN |
| RISK-030 | 查看其他订单 | 顾客请求或引用他人订单 | 授权缺失、可枚举 ID | 个人资料泄露 | POSSIBLE | CRITICAL | EASY | R4 | 安全负责人 | 10 | OPEN |
| RISK-031 | 越权修改 | 非授权主体修改订单/配置 | 身份和对象级授权缺陷 | 错单、欺诈或破坏 | POSSIBLE | CRITICAL | MODERATE | R4 | 安全负责人 | 10 | OPEN |
| RISK-032 | Webhook 重放 | 有效商家事件被重复或跨单应用 | 无签名时效、nonce 或幂等 | 重复状态/订单 | POSSIBLE | CRITICAL | HARD | R4 | 商家集成负责人 | 8 | OPEN |
| RISK-033 | 伪造商家确认 | 非商家来源制造 accepted | 签名、来源或关联验证失败 | 虚假成功 | POSSIBLE | CRITICAL | HARD | R4 | 商家集成负责人 | 8 | OPEN |
| RISK-034 | 恶意长通话 | 攻击者无限占用电话/模型资源 | 无配额、超时或滥用检测 | 服务不可用、成本上升 | LIKELY | MEDIUM | EASY | R2 | 运营负责人 | 7 | OPEN |
| RISK-035 | 重复请求 | 并发/恶意重复消息产生重复动作 | 去重和锁不足 | 重复修改或提交 | LIKELY | CRITICAL | MODERATE | R4 | 平台负责人 | 4 | OPEN |
| RISK-036 | 日志注入 | 顾客文本伪造日志结构或敏感字段 | 未结构化/未转义记录 | 审计欺骗、告警污染 | POSSIBLE | HIGH | MODERATE | R3 | 安全负责人 | 10 | OPEN |
| RISK-037 | 密钥泄露 | API key/token 出现在仓库、日志或回复 | 硬编码、异常或提示泄露 | 外部系统被滥用 | UNLIKELY | CRITICAL | MODERATE | R4 | 安全负责人 | 10 | OPEN |
| RISK-038 | 人工无人接听 | 高风险会话无法接通人工 | 排班、容量或队列故障 | 顾客无安全完成路径 | LIKELY | HIGH | EASY | R3 | 运营负责人 | 9 | OPEN |
| RISK-039 | 商家系统不可用 | 提交或状态查询不可用 | 网络、POS 或供应商故障 | 订单未知/丢失 | LIKELY | HIGH | EASY | R3 | 商家集成负责人 | 8 | OPEN |
| RISK-040 | 菜单过期 | 菜单、价格或营业信息陈旧 | 同步/版本治理不足 | 错菜、错价或错误承诺 | LIKELY | HIGH | MODERATE | R3 | 菜单负责人 | 3 | OPEN |
| RISK-041 | 售罄未同步 | 已售罄菜品仍可选 | 实时库存非范围、更新延迟 | 商家拒单、顾客失望 | LIKELY | HIGH | EASY | R3 | 餐厅运营负责人 | 3 | OPEN |
| RISK-042 | 电话中断 | 音频连接在确认/提交附近中断 | 网络或平台故障 | 确认不明、重复订单 | LIKELY | HIGH | MODERATE | R3 | 电话负责人 | 7 | OPEN |
| RISK-043 | ASR/TTS 不可用 | 无法识别或播报 | 模型、硬件、语言或供应商故障 | 无障碍下降、误解 | LIKELY | MEDIUM | EASY | R2 | 语音负责人 | 6 | OPEN |
| RISK-044 | 成本异常 | 电话/模型/短信成本异常增长 | 滥用、重试、路由或价格变化 | 预算失控 | POSSIBLE | MEDIUM | EASY | R2 | 财务/平台负责人 | 12 | OPEN |
| RISK-045 | 系统降级失败 | 依赖故障后仍执行不安全动作 | 降级设计或状态保护不足 | 错单、虚假成功或泄露 | POSSIBLE | HIGH | HARD | R3 | 平台负责人 | 11 | OPEN |
| RISK-046 | 完整银行卡资料被收集 | 对话、日志或摘要保存卡号/安全码 | 支付边界不清或人工索取 | 欺诈与高敏支付风险 | POSSIBLE | CRITICAL | MODERATE | R4 | 支付安全负责人 | 10 | OPEN |

## 2. 控制、检测、兜底与追踪

| risk_id | preventive_controls | detective_controls | fallback | related_metrics | related_scenarios |
|---|---|---|---|---|---|
| RISK-001 | 权威菜单匹配；模糊候选 `CONFIRM` | 菜品金标与草稿 diff | 澄清后仍模糊则 `HANDOFF` | METRIC-009,METRIC-012 | SCENARIO-002,SCENARIO-010 |
| RISK-002 | 数量/量词单独解析；大幅变化确认 | 数量金标、异常数量告警 | 不确定不修改并 `HANDOFF` | METRIC-010,METRIC-012 | SCENARIO-003,SCENARIO-011 |
| RISK-003 | 价格只读服务层；总价复述 | 价格版本与订单快照核对 | `PRICE_UNAVAILABLE` | METRIC-011,METRIC-017 | SCENARIO-001,SCENARIO-012 |
| RISK-004 | 地址候选不直接采用；逐字段复述 | 地址确认 audit/diff | `UNVERIFIED_ADDRESS` | METRIC-004,METRIC-016 | SCENARIO-006,SCENARIO-074 |
| RISK-005 | 强制 restaurant/branch 绑定且不可隐式切换 | 跨门店不变量与审计 | 阻止提交并安全升级 | METRIC-005,METRIC-011 | SCENARIO-039,SCENARIO-107 |
| RISK-006 | 确认版本+幂等键+商家去重 | 重试/订单关联监控 | 查询权威状态后 `HANDOFF` | METRIC-003,METRIC-017 | SCENARIO-030,SCENARIO-064 |
| RISK-007 | 提交 guard 验证当前确认 | confirmation bypass 计数 | 阻止提交并重新 `CONFIRM` | METRIC-001,METRIC-002 | SCENARIO-007,SCENARIO-032 |
| RISK-008 | 接受只来自权威明确状态 | 状态语义 fixture/审计 | `MERCHANT_TIMEOUT/REJECTED` | METRIC-007,METRIC-017 | SCENARIO-024,SCENARIO-032 |
| RISK-009 | allergy 独立高敏字段；严重词立即接管 | 高风险接管召回测试 | `SEVERE_ALLERGY` | METRIC-006,METRIC-014 | SCENARIO-016,SCENARIO-050 |
| RISK-010 | 分开 allergy/intolerance/preference | 分类混淆矩阵 | 复述并 `CONFIRM` | METRIC-014,METRIC-015 | SCENARIO-018,SCENARIO-052 |
| RISK-011 | allergy 不得映射普通 note | 字段和接管原因断言 | `SEVERE_ALLERGY` | METRIC-006,METRIC-014 | SCENARIO-016,SCENARIO-084 |
| RISK-012 | 配料/过敏原只来自餐厅权威数据 | 缺失数据和虚构答案测试 | `MENU_DATA_MISSING` | METRIC-006,METRIC-009 | SCENARIO-012,SCENARIO-034 |
| RISK-013 | 禁止安全保证；厨房核实 | 禁止话术扫描、高风险场景 | 拒绝保证并 `CROSS_CONTAMINATION` | METRIC-006,METRIC-014 | SCENARIO-017,SCENARIO-034 |
| RISK-014 | 订单变化使确认和食安核实失效 | 版本/过敏检查审计 | 重新接管和确认 | METRIC-002,METRIC-006 | SCENARIO-008,SCENARIO-042 |
| RISK-015 | 独立粤语评测和 locale 证据 | 分语言混淆矩阵 | `LANGUAGE_UNSUPPORTED` | METRIC-009,METRIC-013 | SCENARIO-015,SCENARIO-049 |
| RISK-016 | 菜名、别名和繁简映射唯一性校验 | 菜单冲突 lint | `AMBIGUOUS_ITEM` | METRIC-009 | SCENARIO-010,SCENARIO-044 |
| RISK-017 | mixed 专属语料和实体保留 | 代码切换金标 | 澄清或 `LANGUAGE_UNSUPPORTED` | METRIC-009,METRIC-013 | SCENARIO-083,SCENARIO-117 |
| RISK-018 | 数字绑定字段和币种/量词确认 | 数字混淆矩阵 | `AMBIGUOUS_QUANTITY` | METRIC-010,METRIC-011 | SCENARIO-011,SCENARIO-113 |
| RISK-019 | 地址领域识别；地址与菜名分域 | 地址音近场景 | `UNVERIFIED_ADDRESS` | METRIC-016 | SCENARIO-006,SCENARIO-108 |
| RISK-020 | locale 切换不重置订单；上下文版本化 | 切换前后状态 diff | `LANGUAGE_UNSUPPORTED` | METRIC-004,METRIC-013 | SCENARIO-015,SCENARIO-083 |
| RISK-021 | UI/日志/摘要电话掩码 | 敏感模式扫描和访问审计 | 遏制、撤销访问、事件评估 | METRIC-004,METRIC-005 | SCENARIO-006,SCENARIO-108 |
| RISK-022 | 地址字段级权限与脱敏 | DLP/跨会话测试 | 遏制并进入数据事件流程 | METRIC-004,METRIC-005 | SCENARIO-006,SCENARIO-028 |
| RISK-023 | raw audio 默认不持久化；期限配置 | 存储清单和到期清理监控 | 停止采集并清理未授权副本 | METRIC-005,METRIC-031 | SCENARIO-026,SCENARIO-128 |
| RISK-024 | 结构化日志；禁止完整 transcript | 日志敏感模式扫描 | 停止日志管道并事件响应 | METRIC-005,METRIC-008 | SCENARIO-026,SCENARIO-094 |
| RISK-025 | 环境/凭据/存储隔离；合成标记 | 生产数据和 fixture 扫描 | 隔离环境并调查清理 | METRIC-004,METRIC-005 | SCENARIO-025,SCENARIO-093 |
| RISK-026 | restaurant 级授权和对象过滤 | 跨餐厅负向测试 | `REFUSE`、遏制和安全升级 | METRIC-005 | SCENARIO-028,SCENARIO-062 |
| RISK-027 | 数据索引、期限任务和处理者删除契约 | 删除抽样和逾期告警 | 人工定位、冻结扩散并补删 | METRIC-005 | SCENARIO-025,SCENARIO-127 |
| RISK-028 | 强认证、最小权限、短期凭据 | 访问审计和异常行为检测 | 撤销、`REFUSE`、事件响应 | METRIC-005 | SCENARIO-028,SCENARIO-096 |
| RISK-029 | 指令/数据隔离；规则和权限不可覆盖 | 注入攻击场景、LLM guard | `REFUSE` 并安全升级 | METRIC-008,METRIC-011 | SCENARIO-027,SCENARIO-061 |
| RISK-030 | 当前主体和订单对象授权 | 枚举/他单访问测试 | `REFUSE` 并记录审计 | METRIC-004,METRIC-005 | SCENARIO-029,SCENARIO-063 |
| RISK-031 | 对象级授权；所有修改经 Orchestrator | 越权修改和状态 diff | `REFUSE`、回滚、事件响应 | METRIC-004,METRIC-005 | SCENARIO-028,SCENARIO-096 |
| RISK-032 | webhook 签名、时效、nonce、幂等 | 重放检测和事件关联 | 忽略重放、查询权威状态 | METRIC-003,METRIC-007 | SCENARIO-030,SCENARIO-064 |
| RISK-033 | 商家身份验签和订单关联 | 假 accepted fixture | 不采纳并 `HANDOFF` | METRIC-007,METRIC-017 | SCENARIO-024,SCENARIO-032 |
| RISK-034 | 通话/请求配额和无活动超时 | 时长、速率和成本告警 | 安全终止并提供正常渠道 | METRIC-026,METRIC-027 | SCENARIO-030,SCENARIO-031 |
| RISK-035 | 会话锁、请求去重和幂等 mutation | 重复消息/并发测试 | 丢弃重复并核对草稿 | METRIC-003,METRIC-012 | SCENARIO-030,SCENARIO-064 |
| RISK-036 | 结构化日志、字段转义和长度限制 | 日志解析完整性测试 | 丢弃危险字段并安全升级 | METRIC-005,METRIC-008 | SCENARIO-031,SCENARIO-065 |
| RISK-037 | Secret Manager；禁止硬编码和回显 | secret scan、轮换审计 | 立即撤销轮换并事件响应 | METRIC-008 | SCENARIO-027,SCENARIO-061 |
| RISK-038 | 排班/容量/队列健康和失败话术 | 队列 SLO 和合成接管探针 | 明确失败、保留草稿、授权后回拨 | METRIC-014,METRIC-029 | SCENARIO-022,SCENARIO-056 |
| RISK-039 | 商家健康检查、超时和断路器 | POS 状态和合成探针 | pending/failed，`HANDOFF` | METRIC-007,METRIC-024 | SCENARIO-023,SCENARIO-025 |
| RISK-040 | 菜单版本、更新时间和发布校验 | 陈旧版本/价格差异监控 | 停止报价并 `MENU_DATA_MISSING` | METRIC-009,METRIC-011 | SCENARIO-001,SCENARIO-012 |
| RISK-041 | 可售状态权威更新和提交前复核 | 拒单原因/售罄差异统计 | 提供替代并重新确认或接管 | METRIC-009,METRIC-018 | SCENARIO-013,SCENARIO-047 |
| RISK-042 | 轮次/确认版本/提交幂等 | 中断点恢复测试 | 说明未知、查询状态、禁止重复提交 | METRIC-002,METRIC-003 | SCENARIO-026,SCENARIO-060 |
| RISK-043 | 能力探测、清晰降级和语言支持检查 | ASR/TTS 健康与延迟指标 | 文本渠道或 `HANDOFF` | METRIC-013,METRIC-019,METRIC-022 | SCENARIO-015,SCENARIO-026 |
| RISK-044 | 成本标签、配额和预算阈值 | 分项成本异常检测 | 限流、停用非必要组件、人工审查 | METRIC-026,METRIC-027,METRIC-031 | SCENARIO-030,SCENARIO-064 |
| RISK-045 | fail-closed 降级；副作用 guard 独立 | 故障注入和状态不变量 | 冻结副作用并 `SYSTEM_FAILURE` | METRIC-001,METRIC-007,METRIC-011 | SCENARIO-025,SCENARIO-093 |
| RISK-046 | 对话层拒收完整卡号/CVV；支付隔离 | 敏感支付模式扫描 | `REFUSE`、不回显并 `PAYMENT_DISPUTE` | METRIC-005,METRIC-008 | SCENARIO-033,SCENARIO-067 |

## 3. 高严重度闸门

`HIGH` 和 `CRITICAL` 风险在关闭前必须有已实现的预防控制、检测控制、通过的关联场景、可计算指标、负责人和后续阶段证据。只有文档描述不构成风险关闭。任何 `CRITICAL` 风险出现一次阻塞事件都应停止发布候选；`RISK-009`、`RISK-011`、`RISK-013` 和 `RISK-014` 不能通过降低分类或改写为普通备注来规避。
