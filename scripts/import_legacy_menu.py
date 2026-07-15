from __future__ import annotations

# The legacy JSON import is intentionally implemented by the idempotent Phase 2
# simulation seed. The JSON remains an import/recovery input, never runtime truth.
from seed_phase2_simulation_data import main


if __name__ == "__main__":
    raise SystemExit(main())
