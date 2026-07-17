# 阶段 2：统一业务模型和持久化

阶段 2 将静态 JSON 菜单、内存 session 和 mock 提交升级为可持久化的合成餐厅模拟系统。运行时事实来自数据库服务层；原 JSON 仅作初始导入、fixture 和恢复输入。

当前仍未连接真实餐厅、POS、电话、短信、支付、库存或顾客数据。顾客确认后的准确语义是：“订单已确认并保存到模拟系统，尚未发送给真实餐厅。”

## 文档索引

- [领域模型](domain-model.md)
- [数据库设计与迁移](database-design.md)
- [订单生命周期](order-lifecycle.md)
- [租户隔离](tenant-isolation.md)
- [菜单版本化](menu-versioning.md)
- [本地 PostgreSQL](local-postgres.md)
- [验证矩阵](verification-matrix.md)
- [完成性与数据完整性审计](completion-audit.md)

## 分层与事务边界

`domain` 定义枚举、不变量和稳定错误；`db` 定义 SQLAlchemy Base、engine/session 和 ORM；`repositories` 是唯一 SQL 查询层；`services` 管理 Unit of Work 和业务事务；Agent 只调用服务；API 只解析请求和返回安全错误。Orchestrator 仍是唯一语义和状态修改入口。

## 运行边界

- SQLite 仅用于本机开发和快速回归；PostgreSQL 17.5 是生产目标语义并由 CI service 验证。
- 菜单采用 restaurant-wide 单一发布契约：调用方不选择分店；发布事务切换该餐厅全部 active、未删除分店。
- `session_key` 全局首次绑定，数据库全局唯一；后续租户不匹配只返回通用 `TENANT_CONTEXT_MISMATCH`。
- 金额全部是整数最小币种单位；时间默认写入 UTC，营业计算使用 branch IANA 时区。
- 只有 `development + SQLite + AUTO_MIGRATE_LOCAL=true` 可自动迁移和 seed；没有自动生产迁移。
- `SIMULATION_DATA_ONLY=true` 拒绝未明确标记 synthetic 的 Customer 或 Order。

## 保证层级

- 数据库约束：跨租户/跨版本复合外键、全局 session 唯一、同餐厅单一 `PUBLISHED` 菜单、金额/状态检查。
- Service 校验：菜单发布事务、modifier required/min/max/active/归属/消歧、确认失效、生命周期和幂等冲突。
- Repository 过滤：菜单、订单和幂等读取始终携带 branch/restaurant/version 上下文；过滤不是数据库完整性的替代品。
- 文档约定：synthetic-only 数据和阶段边界；无运行时或数据库证据的能力不得标为已实现。
- 未来阶段：真实电话、POS、支付、短信、商家接受、人工接管运行时和真实资料仍不在阶段 2。

## 阶段 3 进入条件

阶段 3 可在本阶段 Draft PR 审阅通过、Windows/ PostgreSQL CI 全绿、隔离指标继续为 0，且餐厅菜单负责人对过敏原声明契约完成审阅后进入。阶段 3 只定义接管核心和餐厅策略契约，不因本数据模型自动获得真实回拨、餐厅接受或生产数据权限。

## 完成性审计验证

- 本机/Windows：backend `908 passed, 1 PostgreSQL-only skipped`；Phase 1 `140/140`；V3 `57/57`；Vitest `69/69`；typecheck/build 通过。
- PostgreSQL 17.5：Phase 2 `76 passed`，无 skip；空库 head、`20260716_0002 → head → 0002 → head` 和 metadata/约束回归通过。
- false mutation、confirmation bypass、live LLM trigger 均为 0；pip/npm audit 均为 0 已知漏洞。
- 首轮审计实现 CI 为 [run #20](https://github.com/Blank-white-new/Order-agent/actions/runs/29563944397)，Windows 与 PostgreSQL job 均为 success。
