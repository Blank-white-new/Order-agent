# V3 对话评估集 schema

`dialogues_v3.jsonl` 使用 UTF-8 JSONL：每个非空行是一条独立对话样本。JSONL 适合逐条审阅、版本比较和按行定位 schema 错误。

## 顶层字段

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `id` | string | 是 | 稳定且全局唯一的样本 ID，格式建议为 `v3-<category>-NNN`。ID 发布后不要复用。 |
| `category` | enum | 是 | 场景分类，见下表。 |
| `expected_result_type` | enum | 是 | 样本主要评估目标，见下表。 |
| `turns` | array | 是 | 非空的多轮用户输入数组，按顺序在同一个独立 session 中执行。 |
| `expected` | object | 是 | 对最终状态和计分轮行为的断言。 |
| `notes` | string | 否 | 设计意图、边界条件或测试数据说明。 |

每个 `turns` 元素必须有非空 `user` 字符串；可选 `evaluate` 布尔值默认为 `true`。`evaluate:false` 表示该轮只负责建立上下文，其结果仍会记录，但不会参与 mutation、澄清、拒绝和 fallback 行为断言。最终状态始终取整段对话最后一轮之后的状态。

## category

- `normal_order`：常规单品、多品和选项下单。
- `modify_order`：数量、选项、删除或替换已有商品。
- `recommendation`：预算、忌口、口味、速度或排行推荐。
- `delivery`：地址、电话、配送费、ETA 和自取切换。
- `confirmation`：订单预览、确认提交、暂不提交和取消待确认操作。
- `asr_noise`：模拟 ASR 产生的同音字、错字或量词噪声。runner 仍走现有文本入口，不调用 ASR/TTS。
- `multi_intent`：一个输入包含多个点餐或履约意图。
- `ambiguous_reference`：序号、指示词或最近对象引用。
- `should_clarify`：信息不足，系统应澄清且不得误修改订单。
- `should_reject`：越权、菜单外商品、价格篡改或绕过确认等请求。

## expected_result_type

- `should_pass`：应按给定状态和行为预期正常处理。
- `should_clarify`：主要目标是验证安全澄清。
- `should_reject`：主要目标是验证明确拒绝不安全或越权请求。
- `should_not_mutate`：主要目标是验证问句、推荐或预览不会修改订单。

该字段用于聚合统计，不会替代 `expected` 中的显式断言。某个边界分类中的可解析样本仍可标记为 `should_pass`。

## expected

以下四个布尔字段必填：

| 字段 | 含义 |
| --- | --- |
| `should_mutate_order` | 所有 `evaluate:true` 轮中是否至少应有一次 `current_order` 变化。 |
| `allow_order_mutation` | 这些计分轮是否允许修改订单；为 `false` 时任何订单变化都会计入 false mutation。 |
| `should_clarify` | 计分轮是否至少应产生一次澄清。runner 根据 fallback、`pending_question` 和稳定澄清措辞识别。 |
| `should_reject` | 计分轮是否至少应明确拒绝。runner 根据状态拒绝原因和稳定拒绝措辞识别。 |

可选字段：

- `items`：最终订单商品数组。每项至少写 `name`，可写 `quantity`（默认 1）和必须包含的 `options`。默认要求商品集合精确匹配；`exact_items:false` 可只断言子集。
- `stage`、`fulfillment_type`、`official_delivery_address`、`phone`、`submitted`：对应最终 `SessionState` 字段。
- `final_intent`：最后一个计分轮允许的 intent 字符串，或允许值数组。

runner 还会无条件检查 confirmation bypass：若状态从未提交变为已提交，而该轮 `finalIntent` 不是 `confirm`，样本失败并计入汇总。

## pass/fail 逻辑

每条样本使用全新的 `TextEntryService`、session store 和 session ID。runner 按轮保存输入、回复、route/trace、订单前后状态、受关注状态 diff、mutation、澄清、拒绝与 fallback 标志。

样本只有在以下条件全部满足时才 pass：

1. 必填行为布尔值与实际一致。
2. 禁止订单 mutation 时没有 false mutation。
3. 所有已声明的最终状态字段符合预期。
4. 没有 confirmation bypass。
5. 样本执行过程中没有异常。

单条样本运行异常只会令该样本失败，后续样本继续执行。JSON/字段 schema 错误会在运行前中止整次评估。

## 新增样本

1. 选择最窄的 `category` 和主要 `expected_result_type`。
2. 分配新的稳定 ID，不要重排或复用已有 ID。
3. 把纯准备上下文的轮标为 `evaluate:false`。
4. 明确写出四个必填行为布尔值；只声明真正稳定、可解释的最终状态字段。
5. 运行完整数据集、对应分类和 pytest，确认 schema 与 runner 都能加载。

## 隐私与安全

不得写入真实个人手机号、私人地址、姓名、API key、token、密码或 `.env` 内容。需要电话时仅使用明确的虚构测试号码，例如 `13800000000`；需要地址时使用公共地标或带“测试”字样的虚构楼名。数据集不得包含可识别个人的信息。
