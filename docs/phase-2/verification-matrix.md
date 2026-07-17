# 阶段 2 验证矩阵

| 能力 / 闸门 | 实现证据 | 测试证据 | Phase 1 追溯 |
|---|---|---|---|
| 两餐厅、四分店、synthetic-only | `seed_service.py` | `test_tenant_seed.py`, `test_api_simulation.py` | REQ-002, REQ-019, REQ-029; RISK-025 |
| tenant / branch / session 隔离 | 复合外键、全局 session key、TenantService、scoped repositories | `test_tenant_seed.py`, `test_sessions_idempotency.py`, `test_integrity_audit.py` | REQ-004, REQ-013, REQ-017; RISK-005, RISK-026; METRIC-004/005=0 |
| restaurant-wide 菜单版本发布 | MenuManagementService + Published 部分唯一索引 | `test_menu_versioning.py`, `test_integrity_audit.py` | REQ-023; RISK-003, RISK-012, RISK-040/041 |
| 分店售罄和营业时间 | BranchItemAvailability, OpeningHoursService | `test_operations_and_money.py` | REQ-023; RISK-005, RISK-012 |
| 整数金额和权威重算 | Menu/Operations repositories, OrderPersistenceService | `test_operations_and_money.py`, `test_domain_schema.py` | REQ-023; METRIC-009/011 |
| modifier required/min/max/归属/active/消歧和权威加价 | ModifierSelectionValidator + 复合外键 | `test_integrity_audit.py`, `test_operations_and_money.py` | DEC-004; REQ-009, REQ-014, REQ-018 |
| 价格、名称、modifier、allergen 快照 | OrderItem + item/version/order tenant 复合外键 | `test_menu_versioning.py`, `test_operations_and_money.py`, `test_integrity_audit.py` | DEC-004; REQ-009, REQ-014, REQ-018 |
| session 重启恢复与乐观并发 | PersistentSessionStore | `test_sessions_idempotency.py` | REQ-004, REQ-017; RISK-006/032 |
| 确认绑定 draft version | OrderConfirmation / draft fingerprint | `test_confirmation_lifecycle.py` | REQ-006, REQ-015, REQ-018; METRIC-001/002=0 |
| 幂等隔离和并发唯一 | IdempotencyRecord + DB unique | `test_sessions_idempotency.py` | DEC-003; REQ-017; RISK-006/035/042; METRIC-003=0 |
| 集中生命周期 | OrderLifecycleService + OrderEvent | `test_confirmation_lifecycle.py` | REQ-016, REQ-030; RISK-007/008/033/039 |
| merchant acceptance 防伪 | fixture gate + `NOT_INTEGRATED` | `test_confirmation_lifecycle.py`, API/Frontend tests | METRIC-007=0; SCENARIO-023/024/032 |
| SQLite migration 循环和 metadata 一致 | Alembic `20260717_0003` | `test_migrations.py` 空库、0002/head 循环、冲突拒绝、compare_metadata | 阶段 2 DB 闸门 |
| PostgreSQL migration/repository/并发语义 | CI PostgreSQL 17.5 service | 完整 phase2 套件（含 18 项专项）+ 0002/head 循环 | 不用 SQLite 替代 PostgreSQL 证据 |
| 原有语义和安全回归 | offline guard / Orchestrator | 全 pytest, V3, Phase 1 140 场景 | REQ-001, REQ-005, REQ-012, REQ-028 |

## 仍未实现

三语解析、人工接管运行时、电话语音生产能力、电话平台、POS、真实库存、支付、真实餐厅后台、真实顾客数据、香港真实试点和欧洲部署都不在阶段 2。DEC-001/002/005 仍是 deferred/configurable，不因数据表已存在而视为运行能力。

## 审计计数

| 环境 | 结果 |
|---|---|
| 本机/Windows backend | 908 passed，1 PostgreSQL-only skipped |
| PostgreSQL 17.5 Phase 2 | 76 passed，0 skipped |
| Phase 1 catalog | 140/140 |
| V3 | 57/57；false mutation / confirmation bypass / live LLM trigger = 0 |
| Vitest | 69/69；TypeScript 与 Vite build 通过 |
| 依赖 | pip check、pip-audit、npm audit 通过；0 已知漏洞 |

GitHub Actions 最终证据：[CI run #21](https://github.com/Blank-white-new/Order-agent/actions/runs/29564446124)，run id `29564446124`，HEAD `e99c04f7df9c4dd70bd2b36704bfe148c15fe763`（Windows 与 PostgreSQL 17.5 均 success）。run #20 保留为中间验证记录。
