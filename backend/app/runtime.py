from __future__ import annotations

from pathlib import Path

from app.agents.orchestrator import OrchestratorAgent
from app.db.bootstrap import get_runtime_database
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.menu_service import MenuService
from app.services.order_persistence_service import OrderPersistenceService
from app.services.tenant_service import TenantService
from app.services.text_entry_service import TextEntryService
from app.services.handoff_provider import SimulationHandoffProvider
from app.services.handoff_service import HandoffService
from app.services.safety_audit_service import SafetyAuditService
from app.services.safety_decision_service import SafetyDecisionService
from app.state.session_store import PersistentSessionStore
from app.voice.runtime import create_voice_runtime
from app.i18n.menu_lexicon import MenuLexiconService
from app.i18n.message_catalog import MessageCatalog
from app.i18n.response_renderer import ResponseRenderer
from app.i18n.multilingual_text_service import MultilingualTextService
from app.speech.audio_validator import AudioValidator
from app.speech.config import SpeechSettings
from app.speech.provider_registry import SpeechProviderRegistry
from app.speech.replay_asr_provider import ReplayAsrProvider
from app.speech.replay_tts_provider import ReplayTtsProvider
from app.speech.speech_audit_service import SpeechAuditService
from app.speech.speech_pipeline_service import SpeechPipelineService


database = get_runtime_database()
uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
tenant_service = TenantService(uow_factory, database.settings)
store = PersistentSessionStore(uow_factory, tenant_service)
order_persistence_service = OrderPersistenceService(
    uow_factory,
    tenant_service,
    simulation_data_only=database.settings.simulation_data_only,
)
safety_decision_service = SafetyDecisionService()
safety_audit_service = SafetyAuditService(uow_factory, tenant_service, safety_decision_service)
handoff_provider = SimulationHandoffProvider()
handoff_service = HandoffService(uow_factory, tenant_service, handoff_provider)
message_catalog = MessageCatalog(environment=database.settings.app_env)
multilingual_text_service = MultilingualTextService(
    MenuLexiconService(uow_factory, tenant_service),
    ResponseRenderer(message_catalog),
)


def _orchestrator_for_tenant(restaurant_code: str | None, branch_code: str | None) -> OrchestratorAgent:
    return OrchestratorAgent(
        menu_service=MenuService(
            restaurant_code=restaurant_code,
            branch_code=branch_code,
            database=database,
        )
    )


orchestrator = _orchestrator_for_tenant(None, None)
text_entry_service = TextEntryService(
    store=store,
    orchestrator=orchestrator,
    orchestrator_factory=_orchestrator_for_tenant,
    order_persistence_service=order_persistence_service,
    safety_audit_service=safety_audit_service,
    handoff_service=handoff_service,
    multilingual_text_service=multilingual_text_service,
)
voice_runtime = create_voice_runtime()

repository_root = Path(__file__).resolve().parents[2]
speech_settings = SpeechSettings.from_env(
    app_env=database.settings.app_env,
    simulation_data_only=database.settings.simulation_data_only,
)
speech_validator = AudioValidator(speech_settings)
speech_registry = SpeechProviderRegistry(
    speech_settings,
    asr_providers=(
        ReplayAsrProvider(
            repository_root / "evaluation" / "audio" / "manifests" / "phase5_asr_manifest.jsonl",
            repository_root,
        ),
    ),
    tts_providers=(
        ReplayTtsProvider(
            repository_root / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl",
            repository_root,
        ),
    ),
)
speech_audit_service = SpeechAuditService(uow_factory, tenant_service)
speech_pipeline_service = SpeechPipelineService(
    settings=speech_settings,
    registry=speech_registry,
    text_entry_service=text_entry_service,
    validator=speech_validator,
    audit_service=speech_audit_service,
)
