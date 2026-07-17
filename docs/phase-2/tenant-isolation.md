# 租户与 session 隔离

租户上下文是 restaurant code + branch code。旧前端不传时使用默认 synthetic 上下文 `hk-sim-restaurant-a / central`；新客户端可传 JSON `restaurantId/branchId` 或菜单请求 header `X-Restaurant-Id/X-Branch-Id`。

## 默认拒绝

- repository 查询 order 必须同时带 restaurant_id 和 branch_id；menu 从 branch active version 读取。
- session key 首次创建时绑定 tenant，数据库对 `session_key` 全局唯一；后续任一 code 不一致都是不泄露原租户信息的 `TENANT_CONTEXT_MISMATCH`。
- branch active menu、session branch、order branch/session/customer/delivery zone、OrderItem、availability、allergen 和 idempotency 关键关联有复合外键，不只依赖应用过滤。
- 错误只返回稳定 code/message/status，不返回 SQL、stack 或 DATABASE_URL；他租户资源查询返回未找到或上下文不匹配。

## Session 持久化

`conversation_sessions` 保存 JSON 草稿、locale、tenant、status 和 version。运行时只用 `get_by_session_key` 做全局确定性查询，不再混用 tenant-scoped 唯一和模糊全局查询。并发创建相同 key 由数据库全局唯一收敛为一行。每次保存用 `WHERE id=? AND version=?` 乐观更新；0 row 返回 `SESSION_VERSION_CONFLICT`。事务失败时原 DB 状态不变，调用者对象的 version 也不提前增加。closed session 返回 `SESSION_CLOSED`。重新构造 engine/app 后依然从 DB 恢复草稿。

## 对应阶段 1

| 控制 | 对应 |
|---|---|
| tenant 组合外键与 scoped repository | REQ-004, REQ-013, RISK-005, RISK-026 |
| session 不可切换、乐观并发 | REQ-017, RISK-006, RISK-032 |
| synthetic-only 写入 | REQ-002, REQ-019, REQ-029, RISK-025 |
| 跨 session / 跨餐厅负向测试 | METRIC-004=0, METRIC-005=0 |
