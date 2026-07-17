# 数据库设计与迁移

## 技术选型

- ORM：SQLAlchemy 2.x，同步 session。
- migration：Alembic，初始 revision `20260716_0001`、contact 拆分 revision `20260716_0002`、完整性审计 revision `20260717_0003`。
- PostgreSQL driver：psycopg 3 binary distribution。
- 本机快速开发：SQLite；目标数据库和 CI 集成：PostgreSQL。

ORM 使用命名约束；初始 migration 是显式 `op.create_table/create_index` 操作，不导入当前 ORM、不包 seed、不包本机路径，并有逆序 downgrade。租户查询、active menu、session、order、availability、event 和 idempotency 都有索引或唯一约束。

`20260717_0003` 在增加约束前检查重复 session key、同餐厅多个 Published 菜单及跨版本/跨租户关联；发现冲突即明确失败，不删除、不随机合并数据。它新增：

- item/modifier group、branch availability、item/allergen 的 version/tenant 复合键；
- Order customer/restaurant、delivery zone/branch、OrderItem item/version/order tenant 复合键；
- IdempotencyRecord branch/restaurant 复合键；
- `session_key` 全局唯一约束；
- SQLite/PostgreSQL 同语义的 restaurant Published 部分唯一索引。

SQLAlchemy metadata 与 head schema 通过 Alembic `compare_metadata` 回归测试保持一致。Repository 的 tenant 条件属于读取防线，不替代上述数据库约束。

## 本地 SQLite

```powershell
Copy-Item .env.example .env
.\scripts\init_local_db.ps1
```

脚本仅允许 `APP_ENV=development`、SQLite 和 `SIMULATION_DATA_ONLY=true`；它创建 `.local-run`、执行 `alembic upgrade head`、再幂等 seed，不删除现有库。相对 SQLite URL 统一相对仓库根目录解析。

## 手动迁移

```powershell
$env:DATABASE_URL = "sqlite:///./.local-run/order-agent.db"
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini downgrade base
```

PostgreSQL 使用同一 revision，但必须显式提供 URL 并手动执行。非 development 或非 SQLite 环境的 `AUTO_MIGRATE_LOCAL` 始终无效，不存在不可逆的自动生产迁移。

## SQLite / PostgreSQL 边界

SQLite 用于速度和开发可用性，不被当作 PostgreSQL 并发、约束或事务语义的替代证据。PostgreSQL CI 从空库 upgrade，运行完整 phase2 repository/isolation/versioning/idempotency 套件，再 downgrade/upgrade，并运行 pip-audit。

审计实现 CI [run #20](https://github.com/Blank-white-new/Order-agent/actions/runs/29563944397) 在 PostgreSQL 17.5 上完成 76 项 Phase 2 测试且无 skip，包含并发发布、全局 session 创建、12 类非法写入/领域错误和 0002/head 迁移循环。
