from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.orchestrator import OrchestratorAgent  # noqa: E402
from app.db.config import DatabaseSettings  # noqa: E402
from app.db.session import Database, create_database  # noqa: E402
from app.i18n.menu_lexicon import MenuLexiconService  # noqa: E402
from app.i18n.message_catalog import MessageCatalog  # noqa: E402
from app.i18n.multilingual_text_service import MultilingualTextService  # noqa: E402
from app.i18n.response_renderer import ResponseRenderer  # noqa: E402
from app.repositories.uow import SqlAlchemyUnitOfWork  # noqa: E402
from app.services.handoff_provider import SimulationHandoffProvider  # noqa: E402
from app.services.handoff_service import HandoffService  # noqa: E402
from app.services.menu_service import MenuService  # noqa: E402
from app.services.order_persistence_service import OrderPersistenceService  # noqa: E402
from app.services.phase4_menu_seed_service import Phase4MenuSeedService  # noqa: E402
from app.services.safety_audit_service import SafetyAuditService  # noqa: E402
from app.services.safety_decision_service import SafetyDecisionService  # noqa: E402
from app.services.seed_service import seed_phase2_simulation_data  # noqa: E402
from app.services.tenant_service import TenantService  # noqa: E402
from app.services.text_entry_service import TextEntryService  # noqa: E402
from app.speech.audio_validator import AudioValidator  # noqa: E402
from app.speech.config import SpeechSettings  # noqa: E402
from app.speech.provider_registry import SpeechProviderRegistry  # noqa: E402
from app.speech.replay_asr_provider import ReplayAsrProvider  # noqa: E402
from app.speech.replay_tts_provider import ReplayTtsProvider  # noqa: E402
from app.speech.speech_audit_service import SpeechAuditService  # noqa: E402
from app.speech.speech_pipeline_service import SpeechPipelineService  # noqa: E402
from app.state.session_store import PersistentSessionStore  # noqa: E402


@dataclass
class Phase5Context:
    database: Database
    settings: DatabaseSettings
    speech_settings: SpeechSettings
    uow_factory: object
    tenant_service: TenantService
    store: PersistentSessionStore
    text_entry: TextEntryService
    registry: SpeechProviderRegistry
    validator: AudioValidator
    pipeline: SpeechPipelineService


def migrate(database_url: str, revision: str = "head") -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, revision)


def downgrade(database_url: str, revision: str = "base") -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.downgrade(config, revision)


def make_phase5_context(database_url: str) -> Phase5Context:
    database_settings = DatabaseSettings(
        app_env="test",
        database_url=database_url,
        database_echo=False,
        auto_migrate_local=False,
        simulation_data_only=True,
        default_restaurant_code="hk-sim-restaurant-a",
        default_branch_code="central",
    )
    database = create_database(database_settings)
    migrate(database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
    seed_phase2_simulation_data(uow_factory)
    Phase4MenuSeedService(uow_factory).seed()
    tenant_service = TenantService(uow_factory, database_settings)
    store = PersistentSessionStore(uow_factory, tenant_service)
    order_persistence = OrderPersistenceService(
        uow_factory,
        tenant_service,
        simulation_data_only=True,
    )
    safety_decisions = SafetyDecisionService()
    safety_audit = SafetyAuditService(uow_factory, tenant_service, safety_decisions)
    handoff = HandoffService(uow_factory, tenant_service, SimulationHandoffProvider())
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
    speech_settings = SpeechSettings(
        app_env="test",
        simulation_data_only=True,
        asr_provider="replay",
        tts_provider="replay",
        simulation_enabled=True,
        audio_retention_enabled=False,
    )
    validator = AudioValidator(speech_settings)
    registry = SpeechProviderRegistry(
        speech_settings,
        asr_providers=(
            ReplayAsrProvider(
                ROOT / "evaluation" / "audio" / "manifests" / "phase5_asr_manifest.jsonl",
                ROOT,
            ),
        ),
        tts_providers=(
            ReplayTtsProvider(
                ROOT / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl",
                ROOT,
            ),
        ),
    )
    pipeline = SpeechPipelineService(
        settings=speech_settings,
        registry=registry,
        text_entry_service=text_entry,
        validator=validator,
        audit_service=SpeechAuditService(uow_factory, tenant_service),
    )
    return Phase5Context(
        database=database,
        settings=database_settings,
        speech_settings=speech_settings,
        uow_factory=uow_factory,
        tenant_service=tenant_service,
        store=store,
        text_entry=text_entry,
        registry=registry,
        validator=validator,
        pipeline=pipeline,
    )
