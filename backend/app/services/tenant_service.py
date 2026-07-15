from __future__ import annotations

from dataclasses import dataclass

from app.db.config import DatabaseSettings
from app.domain.errors import branch_not_found, restaurant_not_found
from app.repositories.records import TenantRecord
from app.repositories.uow import SqlAlchemyUnitOfWork


@dataclass(frozen=True)
class TenantRequest:
    restaurant_code: str
    branch_code: str


class TenantService:
    def __init__(self, uow_factory, settings: DatabaseSettings) -> None:
        self.uow_factory = uow_factory
        self.settings = settings

    def request(self, restaurant_code: str | None = None, branch_code: str | None = None) -> TenantRequest:
        return TenantRequest(
            restaurant_code=(restaurant_code or self.settings.default_restaurant_code).strip(),
            branch_code=(branch_code or self.settings.default_branch_code).strip(),
        )

    def resolve(self, restaurant_code: str | None = None, branch_code: str | None = None) -> TenantRecord:
        requested = self.request(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            restaurant = uow.tenants.get_restaurant_by_code(requested.restaurant_code)
            if not restaurant:
                raise restaurant_not_found()
            branch = uow.tenants.get_branch(restaurant.id, requested.branch_code)
            if not branch:
                raise branch_not_found()
            return uow.tenants.as_record(restaurant, branch)


def make_uow_factory(session_factory):
    return lambda: SqlAlchemyUnitOfWork(session_factory)
