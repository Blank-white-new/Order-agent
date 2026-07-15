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

## 分层与事务边界

`domain` 定义枚举、不变量和稳定错误；`db` 定义 SQLAlchemy Base、engine/session 和 ORM；`repositories` 是唯一 SQL 查询层；`services` 管理 Unit of Work 和业务事务；Agent 只调用服务；API 只解析请求和返回安全错误。Orchestrator 仍是唯一语义和状态修改入口。

## 运行边界

- SQLite 仅用于本机开发和快速回归；PostgreSQL 17.5 是生产目标语义并由 CI service 验证。
- 金额全部是整数最小币种单位；时间默认写入 UTC，营业计算使用 branch IANA 时区。
- 只有 `development + SQLite + AUTO_MIGRATE_LOCAL=true` 可自动迁移和 seed；没有自动生产迁移。
- `SIMULATION_DATA_ONLY=true` 拒绝未明确标记 synthetic 的 Customer 或 Order。

## 阶段 3 进入条件

阶段 3 可在本阶段 Draft PR 审阅通过、Windows/ PostgreSQL CI 全绿、隔离指标继续为 0，且餐厅菜单负责人对过敏原声明契约完成审阅后进入。阶段 3 只定义接管核心和餐厅策略契约，不因本数据模型自动获得真实回拨、餐厅接受或生产数据权限。
