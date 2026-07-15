from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.bootstrap import get_runtime_database


def main() -> int:
    database = get_runtime_database()
    if database.settings.may_auto_migrate:
        print("Phase 2 development SQLite migration and synthetic seed are ready.")
    else:
        print("Automatic database migration is disabled for this environment/database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
