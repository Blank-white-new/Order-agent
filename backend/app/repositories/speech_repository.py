from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SpeechTurnRecord


class SpeechTurnRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: SpeechTurnRecord) -> None:
        self.session.add(record)

    def list_scoped(
        self,
        session_id: int,
        restaurant_id: int,
        branch_id: int,
    ) -> list[SpeechTurnRecord]:
        return list(
            self.session.scalars(
                select(SpeechTurnRecord)
                .where(
                    SpeechTurnRecord.session_id == session_id,
                    SpeechTurnRecord.restaurant_id == restaurant_id,
                    SpeechTurnRecord.branch_id == branch_id,
                )
                .order_by(SpeechTurnRecord.id)
            )
        )

    def get_scoped(
        self,
        public_id: str,
        restaurant_id: int,
        branch_id: int,
    ) -> SpeechTurnRecord | None:
        return self.session.scalar(
            select(SpeechTurnRecord).where(
                SpeechTurnRecord.public_id == public_id,
                SpeechTurnRecord.restaurant_id == restaurant_id,
                SpeechTurnRecord.branch_id == branch_id,
            )
        )
