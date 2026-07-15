from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import ConversationSession
from app.domain.errors import session_closed, session_version_conflict, tenant_context_mismatch
from app.services.tenant_service import TenantService
from app.state.session_state import SessionState
from app.state.session_persistence import apply_contact, contact_from_state, state_json_without_contact


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get(self, session_id: str, restaurant_code: str | None = None, branch_code: str | None = None) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState()
        return self._sessions[session_id]

    def set(
        self,
        session_id: str,
        state: SessionState,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
    ) -> None:
        self._sessions[session_id] = state

    def reset(self, session_id: str, restaurant_code: str | None = None, branch_code: str | None = None) -> SessionState:
        state = SessionState()
        self._sessions[session_id] = state
        return state


class PersistentSessionStore:
    def __init__(self, uow_factory, tenant_service: TenantService) -> None:
        self.uow_factory = uow_factory
        self.tenant_service = tenant_service

    def get(self, session_id: str, restaurant_code: str | None = None, branch_code: str | None = None) -> SessionState:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            existing = uow.sessions.find_any_tenant(session_id)
            if existing and (existing.restaurant_id != tenant.restaurant_id or existing.branch_id != tenant.branch_id):
                raise tenant_context_mismatch()
            if existing and existing.status == "CLOSED":
                raise session_closed()
            if not existing:
                state = SessionState(
                    restaurant_code=tenant.restaurant_code,
                    branch_code=tenant.branch_code,
                    persistence_version=1,
                    is_synthetic=True,
                )
                existing = ConversationSession(
                    session_key=session_id,
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                    locale="zh-CN",
                    state_json=state_json_without_contact(state),
                    version=1,
                    status="ACTIVE",
                    is_synthetic=True,
                )
                uow.sessions.add(existing)
                uow.flush()
                return state
            state = SessionState(**dict(existing.state_json or {}))
            state.restaurant_code = tenant.restaurant_code
            state.branch_code = tenant.branch_code
            state.persistence_version = existing.version
            state.is_synthetic = existing.is_synthetic
            apply_contact(state, uow.sessions.get_contact(existing.id))
            return state

    def set(
        self,
        session_id: str,
        state: SessionState,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
    ) -> None:
        tenant = self.tenant_service.resolve(
            restaurant_code or state.restaurant_code,
            branch_code or state.branch_code,
        )
        with self.uow_factory() as uow:
            existing = uow.sessions.find_any_tenant(session_id)
            if not existing or existing.restaurant_id != tenant.restaurant_id or existing.branch_id != tenant.branch_id:
                raise tenant_context_mismatch()
            if existing.status == "CLOSED":
                raise session_closed()
            expected_version = state.persistence_version
            state_json = state_json_without_contact(state, persistence_version=expected_version + 1)
            uow.sessions.save_contact(existing.id, **contact_from_state(state))
            saved = uow.sessions.save_optimistic(existing, expected_version, state_json)
            if not saved:
                raise session_version_conflict()
        state.persistence_version = expected_version + 1

    def reset(self, session_id: str, restaurant_code: str | None = None, branch_code: str | None = None) -> SessionState:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            existing = uow.sessions.find_any_tenant(session_id)
            if existing and (existing.restaurant_id != tenant.restaurant_id or existing.branch_id != tenant.branch_id):
                raise tenant_context_mismatch()
            if not existing:
                return SessionState(
                    restaurant_code=tenant.restaurant_code,
                    branch_code=tenant.branch_code,
                    persistence_version=1,
                    is_synthetic=True,
                )
            existing.status = "CLOSED"
            existing.closed_at = datetime.now(timezone.utc)
            existing.version += 1
            existing.state_json = state_json_without_contact(SessionState(), persistence_version=existing.version)
            uow.sessions.save_contact(
                existing.id,
                official_delivery_address=None,
                pending_delivery_address_json=None,
                phone=None,
                is_synthetic=True,
            )
            return SessionState(
                restaurant_code=tenant.restaurant_code,
                branch_code=tenant.branch_code,
                persistence_version=existing.version,
                is_synthetic=True,
            )

