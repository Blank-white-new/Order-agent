from __future__ import annotations

import os

import pytest

from app.services.handoff_provider import SimulationHandoffProvider
from app.services.handoff_service import HandoffService
from app.services.safety_audit_service import SafetyAuditService
from app.services.safety_decision_service import SafetyDecisionService
from tests.phase2.conftest import downgrade, make_context


@pytest.fixture
def phase3(tmp_path):
    database_url = os.getenv("PHASE3_POSTGRES_URL") or os.getenv("PHASE2_POSTGRES_URL")
    database_url = database_url or f"sqlite:///{(tmp_path / 'phase3.db').as_posix()}"
    if database_url.startswith("postgresql"):
        downgrade(database_url)
    context = make_context(database_url)
    decision = SafetyDecisionService()
    audit = SafetyAuditService(context.uow_factory, context.tenant_service, decision)
    provider = SimulationHandoffProvider()
    handoff = HandoffService(context.uow_factory, context.tenant_service, provider)
    context.decision_service = decision
    context.safety_audit_service = audit
    context.handoff_provider = provider
    context.handoff_service = handoff
    try:
        yield context
    finally:
        context.database.engine.dispose()
