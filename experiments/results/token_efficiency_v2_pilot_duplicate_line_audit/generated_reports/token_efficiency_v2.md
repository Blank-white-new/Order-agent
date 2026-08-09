# Selective-LLM Token Efficiency Benchmark v2

## Question

Under a fixed validated decision replay and comparable safety/task outcomes, how much model-specific estimated input and how many invocations are avoided by structured selective LLM use versus direct full-context LLM use?

## Hypothesis

A rules-first structured path should avoid model requests on deterministic and high-risk turns while using the same model interface for genuine ambiguity/fallback turns, reducing prompt volume without changing the common validated expected path.

## Dataset and duplication audit

- 160 synthetic conversations / 868 turns; source dataset unchanged from v1 (`296d6c69c78da67805069d014f9979e08b7d7ef1408cf707c2b398d976454a9d`).
- Locale: 40 each for `zh-CN`, `yue-Hant-HK`, `en-HK`, and `mixed`.
- Scenario: 80 routine, 40 complex, 40 safety.
- Exact and normalized duplicate conversations: 0 / 0.
- There are only **30 semantic template groups**. Ten routine template groups occur eight times; the other 20 groups occur four times. The report therefore includes a 30-cluster bootstrap in addition to a 160-conversation bootstrap.
- Phase 4 source scenarios are reused (maximum reuse 20); this is retained and disclosed, not hidden by regenerating the data.

## Baseline A: reasonable full-context LLM

Every turn invokes the fixed target-model interface. The request contains a concise system instruction, restaurant/branch/locale, core validation policy plus only relevant risk policy, full prior user/assistant history, and current input. It includes all 11 branch menu items only for browse/recommend requests, up to five recalled service-layer candidates for an explicit item reference, and no menu block for unrelated safety/control turns. The downstream schema/menu/state/safety validator is shared with System B.

This is a realistic direct-LLM architecture, not a deliberately padded worst case.

## System B: structured + selective LLM

The unchanged production path owns locale, canonical intents, structured state, menu/policy lookup, and safety. Simulated LLM invocation is allowed only for documented ambiguity codes or the production fallback/low-confidence signal after deterministic safety filtering. Severe allergy, cross-contamination, human/complaint/refund/payment paths, cross-tenant/security refusal, unsupported language, and confirmation/version control never delegate the final action.

The frozen policy and examples are in `experiments/token_efficiency_v2/selective_llm_policy.md`.

## Tokenizer and accounting

- Target model definition: `gpt-4o-mini-2024-07-18`.
- Library: `tiktoken==0.13.0`.
- Runtime mapping: `tiktoken.encoding_for_model(...) -> o200k_base`; vocabulary size 200019.
- Accounting: encoded role/content plus the shared 3-token/message and 3-token/request framing estimate (`tiktoken-o200k-content-plus-3-per-message-plus-3-primer-v1`).
- These are **model-specific estimated input tokens**, not actual billed tokens. No API usage response exists.
- Output tokens are `NOT_MEASURED`; none are invented. Cost is `COST_NOT_EVALUATED`.
- OpenAI's tokenizer page identifies `tiktoken` as the programmatic tokenizer interface: https://platform.openai.com/tokenizer/

## Decision replay and fairness

No live model is called. Both architectures use the same deterministic validated decision replay and independent production executor instances. Phase 4 expected labels are loaded only after prompts and runtime results exist. They are not builder parameters and are never passed to the parser/provider. The frozen multi-turn reference measures replay/validation equivalence; it does **not** measure whether the target model would generate the replayed decision.

Pre-registered quality gate: both blocking-safety counts must be zero and expected-path completion may differ by at most 2 percentage points.

## Task quality

| Metric | Baseline A | System B |
|---|---:|---:|
| Intent | 868/868 (100.00%) | 868/868 (100.00%) |
| Item | 336/336 (100.00%) | 336/336 (100.00%) |
| Quantity | 224/224 (100.00%) | 224/224 (100.00%) |
| Modifier | 44/44 (100.00%) | 44/44 (100.00%) |
| Locale | 834/868 (96.08%) | 834/868 (96.08%) |
| Mutation vs frozen multi-turn reference | 868/868 (100.00%) | 868/868 (100.00%) |
| Expected-path conversation completion | 160/160 (100.00%) | 160/160 (100.00%) |
| Confirmation bypass | 0 | 0 |
| Serious-allergy omission | 0 | 0 |
| False merchant acceptance | 0 | 0 |
| Blocking safety violations | 0 | 0 |

Expected-path gap: **0.00 percentage points**. Both safety gates pass. The 34 locale mismatches are shared contextual mixed-locale outcomes and are retained in error analysis.

## Efficiency results

| Metric | Baseline A | System B | Reduction |
|---|---:|---:|---:|
| Mean input tokens / conversation | 2180.89 | 168.94 | 92.25% |
| Median input tokens / conversation | 1958.50 | 0.00 | paired median reduction 100.00% |
| p95 input tokens / conversation | 3906.20 | 885.25 | - |
| Standard deviation | 1096.81 | 309.94 | - |
| Mean LLM calls / conversation | 5.425 | 0.325 | 94.01% |
| Median LLM calls / conversation | 6.000 | 0.000 | - |
| p95 LLM calls / conversation | 8.050 | 2.000 | - |

- Aggregate paired input-token reduction: **92.25%**.
- Conversation bootstrap 95% CI: **[89.87%, 94.39%]**.
- More conservative 30-template-cluster bootstrap 95% CI: **[86.08%, 96.74%]**.
- Mean paired token difference: **2011.95** tokens/conversation; 95% CI **[1833.23, 2186.91]**.
- Median paired token difference: **1685.50**; 95% CI **[1362.50, 2414.00]**.
- Model-call reduction: **94.01%**; conversation bootstrap 95% CI **[92.13%, 95.69%]** and template-cluster CI **[89.40%, 97.45%]**.

## Stratified results

| Dimension | Group | N | A mean input | B mean input | Reduction | 95% CI | A mean calls | B mean calls | Call reduction |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| scenario_type | complex | 40 | 1960.17 | 555.23 | 71.67% | [65.73%, 77.73%] | 5.300 | 1.100 | 79.25% |
| scenario_type | routine | 80 | 2963.04 | 60.26 | 97.97% | [96.56%, 99.22%] | 7.200 | 0.100 | 98.61% |
| scenario_type | safety | 40 | 837.30 | 0.00 | 100.00% | [100.00%, 100.00%] | 2.000 | 0.000 | 100.00% |
| locale | en-HK | 40 | 2160.68 | 168.70 | 92.19% | [87.22%, 96.37%] | 5.425 | 0.325 | 94.01% |
| locale | mixed | 40 | 2060.45 | 165.97 | 91.94% | [86.82%, 96.23%] | 5.425 | 0.325 | 94.01% |
| locale | yue-Hant-HK | 40 | 2287.70 | 171.38 | 92.51% | [87.65%, 96.52%] | 5.425 | 0.325 | 94.01% |
| locale | zh-CN | 40 | 2214.72 | 169.70 | 92.34% | [87.31%, 96.47%] | 5.425 | 0.325 | 94.01% |

## Complete prompt examples

### Routine example

Input: `给我来一份鸡腿盖饭`

Baseline A input estimate: **390**; System B: **0**; System B reason: `deterministic_high_confidence`.

Baseline A messages:

```json
[
  {
    "content": "You are a multilingual restaurant ordering reasoner.\nFor the current turn, return one structured semantic decision and a concise reply.\nUse only supplied restaurant/menu facts. Preserve quantities and modifiers.\nNever submit without explicit confirmation of the current draft version.\nNever invent merchant acceptance, prices, fees, menu items, staff, or guarantees.\nThe downstream validator owns all state changes and may reject your decision.",
    "role": "system"
  },
  {
    "content": "Restaurant context: {\"branch\":\"central\",\"response_locale\":\"zh-CN\",\"restaurant\":\"hk-sim-restaurant-a\"}",
    "role": "system"
  },
  {
    "content": "Policy context: Required controls: REFUSE outranks HANDOFF, which outranks CONFIRM, which outranks AUTO_DRAFT. Confirmation applies only to the current draft version. All menu, price, availability, delivery-fee, tenant, and merchant-status facts are validated by services.",
    "role": "system"
  },
  {
    "content": "Relevant menu context: [{\"aliases\":[\"机腿饭\",\"鸡腿盖饭\"],\"allergens\":[],\"available\":true,\"base_price_minor\":2600,\"category\":\"饭类\",\"currency\":\"HKD\",\"id\":\"chicken_leg_rice\",\"name\":\"鸡腿饭\",\"options\":[\"不辣\",\"少辣\",\"微辣\",\"大份\",\"加饭\",\"标准\"]}]",
    "role": "system"
  },
  {
    "content": "请给我看菜单",
    "role": "user"
  },
  {
    "content": "菜单有饭类：牛肉饭、黑椒牛肉饭、鸡腿饭、宫保鸡丁饭；面类：番茄鸡蛋面、牛肉面；小吃：酸辣土豆丝、鸡米花；饮品：可乐、雪碧、柠檬茶。",
    "role": "assistant"
  },
  {
    "content": "招牌菜里有什么值得推荐",
    "role": "user"
  },
  {
    "content": "推荐你试试：鸡腿饭26元、番茄鸡蛋面24元、宫保鸡丁饭29元。",
    "role": "assistant"
  },
  {
    "content": "给我来一份鸡腿盖饭",
    "role": "user"
  }
]
```

System B messages:

```json
[]
```

### Complex example

Input: `给我一份鸡腿饭，或者牛肉饭`

Baseline A input estimate: **329**; System B: **444**; System B reason: `semantic_ambiguity:item`.

Baseline A messages:

```json
[
  {
    "content": "You are a multilingual restaurant ordering reasoner.\nFor the current turn, return one structured semantic decision and a concise reply.\nUse only supplied restaurant/menu facts. Preserve quantities and modifiers.\nNever submit without explicit confirmation of the current draft version.\nNever invent merchant acceptance, prices, fees, menu items, staff, or guarantees.\nThe downstream validator owns all state changes and may reject your decision.",
    "role": "system"
  },
  {
    "content": "Restaurant context: {\"branch\":\"central\",\"response_locale\":\"zh-CN\",\"restaurant\":\"hk-sim-restaurant-a\"}",
    "role": "system"
  },
  {
    "content": "Policy context: Required controls: REFUSE outranks HANDOFF, which outranks CONFIRM, which outranks AUTO_DRAFT. Confirmation applies only to the current draft version. All menu, price, availability, delivery-fee, tenant, and merchant-status facts are validated by services.",
    "role": "system"
  },
  {
    "content": "Relevant menu context: [{\"aliases\":[\"牛肉盖饭\"],\"allergens\":[],\"available\":true,\"base_price_minor\":2800,\"category\":\"饭类\",\"currency\":\"HKD\",\"id\":\"beef_rice\",\"name\":\"牛肉饭\",\"options\":[\"不辣\",\"少辣\",\"大份\",\"标准\"]},{\"aliases\":[\"机腿饭\",\"鸡腿盖饭\"],\"allergens\":[],\"available\":true,\"base_price_minor\":2600,\"category\":\"饭类\",\"currency\":\"HKD\",\"id\":\"chicken_leg_rice\",\"name\":\"鸡腿饭\",\"options\":[\"不辣\",\"少辣\",\"微辣\",\"大份\",\"加饭\",\"标准\"]}]",
    "role": "system"
  },
  {
    "content": "给我一份鸡腿饭，或者牛肉饭",
    "role": "user"
  }
]
```

System B messages:

```json
[
  {
    "content": "你是订餐系统的意图解析器。你的任务是把用户输入解析成结构化 JSON。\n只能基于提供的候选菜单、当前订单摘要和上下文。不要编造菜单项，不要编造价格。\n不要输出 Markdown，不要输出解释，只输出 JSON object。不确定时输出 clarify，不要猜。\n如果用户说“这个/那个/刚才那个”，只有上下文唯一明确时才能解析，否则澄清。",
    "role": "system"
  },
  {
    "content": "{\"task\":\"Parse the user's ordering intent into the required JSON object.\",\"schema\":{\"intent\":\"add_item | remove_item | update_quantity | ask_menu | ask_recommendation | delivery | pickup | confirm_order | cancel_order | clarify | smalltalk | unknown\",\"confidence\":\"number from 0 to 1\",\"normalized_text\":\"string or null\",\"actions\":[{\"type\":\"add_item | remove_item | update_quantity | set_delivery | set_pickup | ask_menu | ask_recommendation | confirm_order | cancel_order\",\"item_name\":\"must be from candidate_menu_items or null\",\"quantity\":\"integer 1 to 20 or null\",\"options\":{},\"target\":\"string or null\"}],\"needs_clarification\":\"boolean\",\"clarification_question\":\"string or null\",\"user_facing_reply\":\"string or null\"},\"privacy_rules\":[\"Do not infer or repeat hidden phone/address details.\",\"Do not create menu items or prices.\",\"Do not bypass confirmation.\",\"If input_is_address_like is true, do not output add_item unless the input also has an explicit ordering action.\"],\"current_user_input\":\"给我一份鸡腿饭，或者牛肉饭\",\"input_is_address_like\":false,\"address_present\":false,\"phone_present\":false,\"pending_question\":null,\"pending_action_type\":null,\"order_summary\":[],\"last_recommendations\":[],\"recent_summary\":[\"stage=ordering\",\"fulfillment_type=delivery\"],\"candidate_menu_items\":[{\"name\":\"牛肉饭\",\"category\":\"饭类\",\"aliases\":[\"牛肉盖饭\"],\"available\":true},{\"name\":\"鸡腿饭\",\"category\":\"饭类\",\"aliases\":[\"机腿饭\",\"鸡腿盖饭\"],\"available\":true}]}",
    "role": "user"
  }
]
```

### Safety example

Input: `我有严重过敏，可能过敏性休克`

Baseline A input estimate: **294**; System B: **0**; System B reason: `deterministic_safety:HANDOFF`.

Baseline A messages:

```json
[
  {
    "content": "You are a multilingual restaurant ordering reasoner.\nFor the current turn, return one structured semantic decision and a concise reply.\nUse only supplied restaurant/menu facts. Preserve quantities and modifiers.\nNever submit without explicit confirmation of the current draft version.\nNever invent merchant acceptance, prices, fees, menu items, staff, or guarantees.\nThe downstream validator owns all state changes and may reject your decision.",
    "role": "system"
  },
  {
    "content": "Restaurant context: {\"branch\":\"central\",\"response_locale\":\"zh-CN\",\"restaurant\":\"hk-sim-restaurant-a\"}",
    "role": "system"
  },
  {
    "content": "Policy context: Required controls: REFUSE outranks HANDOFF, which outranks CONFIRM, which outranks AUTO_DRAFT. Confirmation applies only to the current draft version. All menu, price, availability, delivery-fee, tenant, and merchant-status facts are validated by services.\nSevere allergy, anaphylaxis, and cross-contamination requests require deterministic HANDOFF; never guarantee allergen absence.",
    "role": "system"
  },
  {
    "content": "请给我看菜单",
    "role": "user"
  },
  {
    "content": "菜单有饭类：牛肉饭、黑椒牛肉饭、鸡腿饭、宫保鸡丁饭；面类：番茄鸡蛋面、牛肉面；小吃：酸辣土豆丝、鸡米花；饮品：可乐、雪碧、柠檬茶。",
    "role": "assistant"
  },
  {
    "content": "我有严重过敏，可能过敏性休克",
    "role": "user"
  }
]
```

System B messages:

```json
[]
```


## Reproducibility

Runs 1/2/3 retained identical conversation IDs, prompts, token counts, call decisions, quality outcomes, and safety counts. Token-reduction drift = 0.00%; call-reduction drift = 0.00%. Raw CSV, metadata JSON, prompt hashes/examples, frozen reference, paired conversation tables, bootstrap results, and figures are retained under `experiments/results/token_efficiency_v2` and `experiments/reports/figures/token_efficiency_v2`.

## Limitations

- Conversations and decision outputs are synthetic/offline; no live user, restaurant, phone, ASR, or TTS is involved.
- The deterministic decision replay holds semantic quality constant and validates downstream equivalence; it does not measure live `gpt-4o-mini-2024-07-18` accuracy or output naturalness.
- The tokenizer/accounting result is a model-specific estimate, not production billing evidence.
- Thirty semantic template groups and repeated Phase 4 source expressions limit external validity; cluster intervals are reported for that reason.
- No actual API cost, latency, cache behavior, provider retry, or production traffic distribution is measured.

## CV eligibility

**CV_ELIGIBLE_WITH_QUALIFIER**. All technical gates pass, but the mandatory wording must retain `synthetic`, `offline deterministic replay`, and `model-specific estimated input tokens`. It may not claim actual API billing, live-model accuracy, real-user success, or production savings.
