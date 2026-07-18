# Phase 5 评测指标与流程完成审计

## AUDIT-P5-001

- finding：fixture hash 分母包含 AudioValidator 已失败、Replay Provider 未调用的场景。
- impact：旧 `fixture hash 240/240` 把未执行的 lookup/hash 当作成功，夸大覆盖率。
- original_behavior：评测器先在 validation 成功时调用 Provider，但随后对全部 240 条无条件增加 `fixture_hash` 分母；validation 失败时 `provider_code=None` 被当作非 hash mismatch 成功。
- fix：删除独立的 Provider 预检调用，以一次权威 pipeline 调用的 observer event 分层记录 lookup、hash 和 metadata；validation 失败单独验证零调用。
- new_metric：fixture lookup 212/212；fixture SHA-256 208/208；fixture metadata 204/204；validation failure 后 Provider 未调用 28/28；fixture not found 4/4。
- new_test：`test_provider_stage_denominators_follow_actual_execution` 覆盖 validation failure、fixture missing、hash mismatch 和正常 Replay。
- status：VERIFIED

## AUDIT-P5-002

- finding：旧 `audio retention 240/240` 实际只检查每个 Session 有一条 speech audit 记录。
- impact：审计 metadata 存在不能证明 raw audio 未落入数据库或文件系统。
- original_behavior：`speech_audit_count(...) == 1` 同时被当作 audit、retention 和 raw-audio persistence 证据。
- fix：重命名为 speech audit record，并增加 ORM/数据库 schema 禁止列、Binary/BLOB/bytea、逐行 payload/Base64、限定范围临时文件和 retention 配置检查。
- new_metric：speech audit record 240/240；audit schema 20/20；raw audio database 241/241；temporary audio file 3/3；retention configuration 2/2。
- new_test：audit repository schema/content test、retention fail-closed test、API upload snapshot test、evaluator temporary cleanup test。
- status：VERIFIED

## AUDIT-P5-003

- finding：旧 transcript logging 分母包含没有 transcript 的失败场景。
- impact：旧 `transcript logging 240/240` 混合了“实际 transcript 未记录”和“失败时没有伪造 transcript”两种不同保证。
- original_behavior：每条场景先无条件加一次成功，结束后再用 `expectedTranscript` 扫描全局日志并扣减。
- fix：从 `result.transcript.transcript` 决定实际 transcript 分母并扫描该实际值；实际无 transcript 的场景独立扫描 expected/manifest 候选；synthetic 电话、地址、姓名标记独立扫描日志和 trace。
- new_metric：actual transcript log 184/184；no-transcript failure log 56/56；sensitive field log/trace 3/3。
- new_test：actual transcript denominator test、poisoned expected transcript test、sensitive marker evaluation。
- status：VERIFIED

## AUDIT-P5-004

- finding：旧 live Provider 指标通过 `result is None`、`result.transcript is None` 或结果 mode 推断调用模式。
- impact：validation skip 和 Replay failure 被当作“Replay 成功证据”，无法证明调用次数或失败调用模式，也无法发现真实网络尝试。
- original_behavior：未调用、没有 transcript 和 Replay result 都增加同一 `live_provider` 成功计数。
- fix：为 Replay ASR/TTS 增加不进入业务结果的线程安全 invocation observer；每次真实调用均记录 operation/mode/network/success/error；四个网络入口在 Provider 调用期间被替换并计数。
- new_metric：Provider invocation expectation 240/240；Replay ASR invocation 212/212；Provider not invoked 28/28；Provider failure invocation 28/28；live Provider invocation 0；network invocation 0。
- new_test：timeout/error invocation tests、validation zero-call test、四个 network entry-point tests、live-mode observer count test；TTS 也验证 synthesize 15/15 和 missing failure 1/1。
- status：VERIFIED

## AUDIT-P5-005

- finding：旧 `tenant isolation 4/4` 主要是越权文本被分类为 `REFUSE`，没有区分分类、API、Repository 和数据库隔离。
- impact：文本分类正确不能证明错误租户无法读取或写入真实 Session、Order 或 SpeechTurn。
- original_behavior：仅对四条 `cross_tenant` transcript 检查无 mutation 且 classification 为 `REFUSE`。
- fix：保留独立 refusal classification，并新增 Session access、API rebinding、wrong-tenant repository read、cross-tenant SpeechTurn/Order composite-FK negative write和数据库行数不变/响应不泄露检查。
- new_metric：refusal classification 4/4；Session access 1/1；Order reference 1/1；SpeechTurn write 1/1；Repository read 2/2；API rebinding 2/2；data leak failure 0。
- new_test：SQLite/服务层/API 定向测试；相同 Phase 5 persistence/tenant files 在 PostgreSQL 17.5 CI 中执行，验证复合外键真实拒绝。
- status：VERIFIED

## PROCESS-P5-001

- finding：阶段 5 分支曾依次出现 `e9b34d9` → `c582e37` → `65f03d5`，三个同父 HEAD，表明曾发生非快进更新。
- impact：违反本阶段“不得强制推送和改写历史”的流程要求。代码安全和最终 CI 不因此自动失效，但审计链条受到影响。
- original_behavior：阶段 5 已发布分支的 HEAD 曾被同父提交替换，历史事实不可撤销。
- fix：从 `65f03d5` 起，所有评测、测试和文档修正只通过普通追加提交完成；禁止再次 force push；PR 和最终报告永久保留该偏差。
- new_metric：不适用；这是流程偏差，不得表示为代码通过率或“已修复”。
- new_test：每次提交和推送前后核对本地/远端 ancestry、ahead/behind、工作区和 PR head；最终 CI 绑定追加后的最终 HEAD。
- status：RECORDED_PROCESS_DEVIATION

本轮从 `65f03d5ef3127cc762bedc129bccc33affdfe8ef` 开始，没有再次 force push、rebase 或改写原有九个 Phase 5 提交。当前分支状态正常，但阶段 5 存在一次已记录的历史流程偏差。
