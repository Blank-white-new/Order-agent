from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import Branch, MenuVersion
from app.domain.errors import DomainError


class MenuManagementService:
    def __init__(self, uow_factory) -> None:
        self.uow_factory = uow_factory

    def create_draft(self, restaurant_id: int) -> MenuVersion:
        with self.uow_factory() as uow:
            version = MenuVersion(
                restaurant_id=restaurant_id,
                version_number=uow.menus.next_version_number(restaurant_id),
                status="DRAFT",
            )
            uow.menus.add(version)
            uow.flush()
            return version

    def assert_mutable(self, version_id: int) -> None:
        with self.uow_factory() as uow:
            version = uow.menus.get_version(version_id)
            if not version:
                raise DomainError("MENU_VERSION_NOT_FOUND", "Menu version was not found.", 404)
            if version.status != "DRAFT":
                raise DomainError("PUBLISHED_MENU_IMMUTABLE", "Published or archived menu versions cannot be edited.")

    def publish(self, restaurant_id: int, branch_ids: list[int], version_id: int) -> MenuVersion:
        with self.uow_factory() as uow:
            version = uow.menus.get_version(version_id)
            if not version or version.restaurant_id != restaurant_id:
                raise DomainError("MENU_VERSION_NOT_FOUND", "Menu version was not found.", 404)
            if version.status != "DRAFT":
                raise DomainError("PUBLISHED_MENU_IMMUTABLE", "Only a draft menu version can be published.")
            for branch_id in branch_ids:
                branch = uow.tenants.get_branch_by_id(branch_id)
                if not branch or branch.restaurant_id != restaurant_id:
                    raise DomainError("TENANT_CONTEXT_MISMATCH", "A branch cannot publish another restaurant's menu.")
            version.effective_at = version.effective_at or datetime.now(timezone.utc)
            uow.menus.publish(restaurant_id, branch_ids, version)
            uow.flush()
            return version
