from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import ConversationContactSnapshot, ConversationSession


class ConversationSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_any_tenant(self, session_key: str) -> ConversationSession | None:
        return self.session.scalar(select(ConversationSession).where(ConversationSession.session_key == session_key))

    def get(self, session_key: str, restaurant_id: int, branch_id: int) -> ConversationSession | None:
        return self.session.scalar(
            select(ConversationSession).where(
                ConversationSession.session_key == session_key,
                ConversationSession.restaurant_id == restaurant_id,
                ConversationSession.branch_id == branch_id,
            )
        )

    def add(self, entity: ConversationSession) -> None:
        self.session.add(entity)

    def save_optimistic(self, entity: ConversationSession, expected_version: int, state_json: dict) -> bool:
        result = self.session.execute(
            update(ConversationSession)
            .where(ConversationSession.id == entity.id, ConversationSession.version == expected_version)
            .values(state_json=state_json, version=expected_version + 1)
        )
        return result.rowcount == 1

    def get_contact(self, session_id: int) -> ConversationContactSnapshot | None:
        return self.session.scalar(
            select(ConversationContactSnapshot).where(ConversationContactSnapshot.session_id == session_id)
        )

    def save_contact(
        self,
        session_id: int,
        *,
        official_delivery_address: str | None,
        pending_delivery_address_json: dict | None,
        phone: str | None,
        is_synthetic: bool,
    ) -> None:
        snapshot = self.get_contact(session_id)
        if snapshot is None:
            snapshot = ConversationContactSnapshot(session_id=session_id)
            self.session.add(snapshot)
        snapshot.official_delivery_address = official_delivery_address
        snapshot.pending_delivery_address_json = pending_delivery_address_json
        snapshot.phone = phone
        snapshot.is_synthetic = is_synthetic
