from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.config import DatabaseSettings  # noqa: E402
from app.db.session import create_database  # noqa: E402
from app.repositories.uow import SqlAlchemyUnitOfWork  # noqa: E402
from app.services.phase4_menu_seed_service import Phase4MenuSeedService  # noqa: E402


def main() -> int:
    database = create_database(DatabaseSettings.from_env())
    if database.settings.app_env not in {"development", "test"} or not database.settings.simulation_data_only:
        raise RuntimeError("Phase 4 seed is restricted to development/test simulation environments.")
    factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
    summary = Phase4MenuSeedService(factory).seed()
    print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
