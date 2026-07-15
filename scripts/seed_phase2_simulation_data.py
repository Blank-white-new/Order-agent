from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.config import DatabaseSettings
from app.db.session import create_database
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.seed_service import seed_phase2_simulation_data


def main() -> int:
    database = create_database(DatabaseSettings.from_env())
    if database.settings.app_env != "development" or not database.settings.simulation_data_only:
        raise RuntimeError("Phase 2 seed is restricted to development simulation environments.")
    summary = seed_phase2_simulation_data(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
