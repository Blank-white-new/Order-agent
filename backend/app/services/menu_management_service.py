from __future__ import annotations

from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.models import MenuVersion
from app.domain.errors import DomainError, menu_publish_conflict


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

    def publish(self, restaurant_id: int, version_id: int) -> MenuVersion:
        """Publish one restaurant-wide menu and activate it for every active branch."""
        try:
            with self.uow_factory() as uow:
                version = uow.menus.get_version(version_id)
                if not version or version.restaurant_id != restaurant_id:
                    raise DomainError("MENU_VERSION_NOT_FOUND", "Menu version was not found.", 404)
                if version.status != "DRAFT":
                    raise DomainError("PUBLISHED_MENU_IMMUTABLE", "Only a draft menu version can be published.")
                uow.menus.publish_for_restaurant(restaurant_id, version)
                uow.flush()
                return version
        except (IntegrityError, OperationalError) as exc:
            raise menu_publish_conflict() from exc
