# 本地 PostgreSQL 模拟

`compose.phase2.yml` 只启动官方 `postgres:17.5-alpine`，绑定 `127.0.0.1:54329`，使用明确 synthetic local-only 凭据。数据目录是 `.local-run/postgres-data`，已被 `.gitignore` 排除。该配置不是生产配置。

```powershell
docker compose -f compose.phase2.yml up -d
$env:APP_ENV = "test"
$env:AUTO_MIGRATE_LOCAL = "false"
$env:SIMULATION_DATA_ONLY = "true"
$env:DATABASE_URL = "postgresql+psycopg://order_agent_sim:synthetic-local-only-password@127.0.0.1:54329/order_agent_sim"
$env:PHASE2_POSTGRES_URL = $env:DATABASE_URL
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
.\backend\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider backend\tests\phase2
```

验证 downgrade/re-upgrade：

```powershell
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini downgrade base
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

停止服务：

```powershell
docker compose -f compose.phase2.yml down
```

不要对未明确的数据库执行 downgrade，不要将这些 synthetic 凭据复用到其他环境。无 Docker 的开发机不得声称本地 PostgreSQL 已通过；以 GitHub Actions `PostgreSQL 17.5 integration` job 为数据库语义证据。
