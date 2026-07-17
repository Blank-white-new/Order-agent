from __future__ import annotations

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
)
voice_runtime = create_voice_runtime()
