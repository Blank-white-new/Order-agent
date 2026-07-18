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
- fix：从 `result.transcript.transcript` 决定实际 transcript 分母并扫描该实际值；实际无 transcript 且存在 expected/manifest 候选时才进入 candidate log 分母；fixture-not-found 使用独立结构检查；synthetic 电话、地址、姓名标记独立扫描日志和 trace。
- new_metric：actual transcript log 184/184；no-transcript candidate log 52/52；fixture-not-found log structure 4/4；sensitive field log/trace 3/3。
- new_test：actual transcript denominator test、poisoned expected transcript test、empty candidate test、fixture-not-found structure negative tests、sensitive marker evaluation。
- status：VERIFIED

## AUDIT-P5-004

- finding：旧 live Provider 指标通过 `result is None`、`result.transcript is None` 或结果 mode 推断调用模式。
- impact：validation skip 和 Replay failure 被当作“Replay 成功证据”，无法证明调用次数或失败调用模式，也无法发现真实网络尝试。
- original_behavior：未调用、没有 transcript 和 Replay result 都增加同一 `live_provider` 成功计数。
- fix：为 Replay ASR/TTS 增加不进入业务结果的线程安全 invocation observer；每次真实调用均记录 operation/mode/network/success/error；四个受控网络入口只在 Replay Provider 调用栈触达时被阻断并计数。
- new_metric：Provider invocation expectation 240/240；Replay ASR invocation 212/212；Provider not invoked 28/28；Provider failure invocation 28/28；live Provider invocation 0；Replay Provider-origin network invocation 0。
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

## AUDIT-P5-006

- finding：fixture-not-found 场景没有 expected 或 manifest transcript，旧 no-transcript failure 检查通过空候选集合的 `all()` 自动成功。
- impact：4 个场景没有提供实际日志泄漏证据，导致原 56/56 口径把“存在候选且未泄漏”和“根本没有候选”混为同一种成功。
- original_behavior：所有实际无 transcript 的场景都会增加同一分母；fixture-not-found 的 `candidates` 为空时，`all(candidate not in log for candidate in candidates)` 返回 true。
- fix：将有候选 transcript 的失败日志和 fixture-not-found 日志结构拆分。前者只在候选非空时增加分母；后者绑定实际 `SPEECH_FIXTURE_NOT_FOUND`，检查 result/trace、其他 manifest transcript/fixture ID、manifest JSON/路径、仓库绝对路径、audio payload/Base64、订单/确认/幂等记录和允许字段失败审计。
- new_metric：no-transcript candidate log 52/52；fixture-not-found log structure 4/4；两个 failure blocker 均为 0。
- new_test：empty candidate denominator、fixture-not-found independent metric、other transcript leak、absolute path leak、manifest/audio payload leak、valid fixture-not-found structure。
- status：VERIFIED

## AUDIT-P5-007

- finding：旧 network invocation 名称容易被理解为全进程网络审计。
- impact：实际守卫只覆盖 Replay ASR/TTS Provider 调用链中的四个 Python 网络入口，不能代表 PostgreSQL、GitHub Actions、pip/npm 或其他非 Provider 代码没有网络活动。
- original_behavior：输出 `network_invocation` 与 `network_invocations`，文档使用宽泛的 “Network invocations: 0”。
- fix：指标重命名为 Replay Provider-origin network entry point/invocation；守卫类、speech/TTS JSON、Gate、测试、CI 步骤和文档均明确作用范围。
- new_metric：Replay Provider-origin network entry-point checks 4/4；Replay Provider-origin network invocations 0。
- new_test：四个入口从 Replay Provider 调用链触发时均被阻断、计数并产生稳定 Provider failure，订单指纹不变；序列化输出不再包含旧宽泛字段。
- status：VERIFIED

## PROCESS-P5-001

- finding：阶段 5 分支曾依次出现 `e9b34d9` → `c582e37` → `65f03d5`，三个同父 HEAD，表明曾发生非快进更新。
- impact：违反本阶段“不得强制推送和改写历史”的流程要求。代码安全和最终 CI 不因此自动失效，但审计链条受到影响。
- original_behavior：阶段 5 已发布分支的 HEAD 曾被同父提交替换，历史事实不可撤销。
- fix：从 `65f03d5` 起，所有评测、测试和文档修正只通过普通追加提交完成；禁止再次 force push；PR 和最终报告永久保留该偏差。
- new_metric：不适用；这是流程偏差，不得表示为代码通过率或“已修复”。
- new_test：每次提交和推送前后核对本地/远端 ancestry、ahead/behind、工作区和 PR head；最终 CI 绑定追加后的最终 HEAD。
- status：RECORDED_PROCESS_DEVIATION

从 `65f03d5ef3127cc762bedc129bccc33affdfe8ef` 起的所有修正均为普通追加提交；本次小修以 `b572aaf1a19dbf5b486aeeb2fda067824bb3da24` 为起点，同样没有 force push、rebase 或改写已有十二个 Phase 5 提交。当前分支状态正常，但阶段 5 存在一次已记录的历史流程偏差。
