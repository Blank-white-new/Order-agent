# 阶段 2 验证矩阵

| 能力 / 闸门 | 实现证据 | 测试证据 | Phase 1 追溯 |
|---|---|---|---|
| 两餐厅、四分店、synthetic-only | `seed_service.py` | `test_tenant_seed.py`, `test_api_simulation.py` | REQ-002, REQ-019, REQ-029; RISK-025 |
| tenant / branch / session 隔离 | 组合外键、TenantService、scoped repositories | `test_tenant_seed.py`, `test_sessions_idempotency.py` | REQ-004, REQ-013, REQ-017; RISK-005, RISK-026; METRIC-004/005=0 |
| 菜单版本发布 | MenuManagementService | `test_menu_versioning.py` | REQ-023; RISK-003, RISK-012, RISK-040/041 |
| 分店售罄和营业时间 | BranchItemAvailability, OpeningHoursService | `test_operations_and_money.py` | REQ-023; RISK-005, RISK-012 |
| 整数金额和权威重算 | Menu/Operations repositories, OrderPersistenceService | `test_operations_and_money.py`, `test_domain_schema.py` | REQ-023; METRIC-009/011 |
| 价格、名称、modifier、allergen 快照 | OrderItem | `test_menu_versioning.py`, `test_operations_and_money.py` | DEC-004; REQ-009, REQ-014, REQ-018 |
| session 重启恢复与乐观并发 | PersistentSessionStore | `test_sessions_idempotency.py` | REQ-004, REQ-017; RISK-006/032 |
| 确认绑定 draft version | OrderConfirmation / draft fingerprint | `test_confirmation_lifecycle.py` | REQ-006, REQ-015, REQ-018; METRIC-001/002=0 |
| 幂等隔离和并发唯一 | IdempotencyRecord + DB unique | `test_sessions_idempotency.py` | DEC-003; REQ-017; RISK-006/035/042; METRIC-003=0 |
| 集中生命周期 | OrderLifecycleService + OrderEvent | `test_confirmation_lifecycle.py` | REQ-016, REQ-030; RISK-007/008/033/039 |
| merchant acceptance 防伪 | fixture gate + `NOT_INTEGRATED` | `test_confirmation_lifecycle.py`, API/Frontend tests | METRIC-007=0; SCENARIO-023/024/032 |
| SQLite migration 循环 | Alembic revision | `test_migrations.py` | 阶段 2 DB 闸门 |
| PostgreSQL migration/repository 语义 | CI PostgreSQL service | phase2 套件 + downgrade/upgrade job | 不用 SQLite 替代 PostgreSQL 证据 |
| 原有语义和安全回归 | offline guard / Orchestrator | 全 pytest, V3, Phase 1 140 场景 | REQ-001, REQ-005, REQ-012, REQ-028 |

## 仍未实现

三语解析、人工接管运行时、电话语音生产能力、电话平台、POS、真实库存、支付、真实餐厅后台、真实顾客数据、香港真实试点和欧洲部署都不在阶段 2。DEC-001/002/005 仍是 deferred/configurable，不因数据表已存在而视为运行能力。
