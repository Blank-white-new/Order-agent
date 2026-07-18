from __future__ import annotations

import os

import pytest

from evaluation.phase5_harness import downgrade, make_phase5_context


@pytest.fixture(scope="session")
def phase5(tmp_path_factory):
    database_url = os.getenv("PHASE5_POSTGRES_URL") or (
        f"sqlite:///{(tmp_path_factory.mktemp('phase5') / 'phase5.db').as_posix()}"
    )
    if database_url.startswith("postgresql"):
        downgrade(database_url)
    context = make_phase5_context(database_url)
    try:
        yield context
    finally:
        context.database.engine.dispose()
