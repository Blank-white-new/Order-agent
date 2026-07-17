from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.agents.orchestrator import OrchestratorAgent
from app.db.config import DatabaseSettings
from app.db.session import Database, create_database
from app.i18n.menu_lexicon import MenuLexiconService
from app.i18n.message_catalog import MessageCatalog
from app.i18n.multilingual_text_service import MultilingualTextService
from app.i18n.response_renderer import ResponseRenderer
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.handoff_provider import SimulationHandoffProvider
from app.services.handoff_service import HandoffService
from app.services.menu_service import MenuService
from app.services.order_persistence_service import OrderPersistenceService
from app.services.phase4_menu_seed_service import Phase4MenuSeedService
from app.services.safety_audit_service import SafetyAuditService
from app.services.safety_decision_service import SafetyDecisionService
from app.services.seed_service import seed_phase2_simulation_data
from app.services.tenant_service import TenantService
from app.services.text_entry_service import TextEntryService
from app.state.session_store import PersistentSessionStore


BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Phase4Context:
    database: Database
    settings: DatabaseSettings
    uow_factory: object
    tenant_service: TenantService
    store: PersistentSessionStore
    text_entry: TextEntryService
    seed_summary: object


def migrate(database_url: str, revision: str = "head") -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, revision)


def downgrade(database_url: str, revision: str = "base") -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.downgrade(config, revision)


def make_phase4_context(database_url: str) -> Phase4Context:
    settings = DatabaseSettings(
        app_env="test",
        database_url=database_url,
        database_echo=False,
        auto_migrate_local=False,
        simulation_data_only=True,
        default_restaurant_code="hk-sim-restaurant-a",
        default_branch_code="central",
    )
    database = create_database(settings)
    migrate(database.settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
    seed_phase2_simulation_data(uow_factory)
    seed_summary = Phase4MenuSeedService(uow_factory).seed()
    tenant_service = TenantService(uow_factory, database.settings)
    store = PersistentSessionStore(uow_factory, tenant_service)
    order_persistence = OrderPersistenceService(
        uow_factory, tenant_service, simulation_data_only=True
    )
    safety_decisions = SafetyDecisionService()
    safety_audit = SafetyAuditService(uow_factory, tenant_service, safety_decisions)
    handoff = HandoffService(
        uow_factory, tenant_service, SimulationHandoffProvider()
    )
    multilingual = MultilingualTextService(
        MenuLexiconService(uow_factory, tenant_service),
        ResponseRenderer(MessageCatalog(environment="test")),
    )

    def orchestrator_for_tenant(restaurant_code, branch_code):
        return OrchestratorAgent(
            menu_service=MenuService(
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                database=database,
            )
        )

    text_entry = TextEntryService(
        store=store,
        orchestrator=orchestrator_for_tenant(None, None),
        orchestrator_factory=orchestrator_for_tenant,
        order_persistence_service=order_persistence,
        safety_audit_service=safety_audit,
        handoff_service=handoff,
        multilingual_text_service=multilingual,
    )
    return Phase4Context(
        database=database,
        settings=database.settings,
        uow_factory=uow_factory,
        tenant_service=tenant_service,
        store=store,
        text_entry=text_entry,
        seed_summary=seed_summary,
    )


@pytest.fixture(scope="session")
def phase4(tmp_path_factory):
    database_url = os.getenv("PHASE4_POSTGRES_URL") or (
        f"sqlite:///{(tmp_path_factory.mktemp('phase4') / 'phase4.db').as_posix()}"
    )
    if database_url.startswith("postgresql"):
        downgrade(database_url)
    context = make_phase4_context(database_url)
    try:
        yield context
    finally:
        context.database.engine.dispose()
