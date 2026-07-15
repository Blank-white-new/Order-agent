from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.menu_repository import MenuRepository
from app.repositories.operations_repository import OperationsRepository
from app.repositories.order_repository import IdempotencyRepository, OrderRepository
from app.repositories.session_repository import ConversationSessionRepository
from app.repositories.tenant_repository import TenantRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self.session_factory()
        self.session.begin()
        self.tenants = TenantRepository(self.session)
        self.menus = MenuRepository(self.session)
        self.sessions = ConversationSessionRepository(self.session)
        self.orders = OrderRepository(self.session)
        self.idempotency = IdempotencyRepository(self.session)
        self.operations = OperationsRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self.session is not None
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()

    def flush(self) -> None:
        assert self.session is not None
        self.session.flush()

    def rollback(self) -> None:
        assert self.session is not None
        self.session.rollback()
