from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.i18n.locales import CONCRETE_LOCALES
from app.services.menu_management_service import MenuManagementService


CATALOG_PATH = Path(__file__).parents[1] / "i18n" / "catalogs" / "multilingual_menu.json"


@dataclass
class Phase4SeedSummary:
    restaurants: int = 0
    menu_versions_created: int = 0
    idempotent_restaurants: int = 0
    categories: int = 0
    items: int = 0
    aliases: int = 0
    modifier_options: int = 0
    published_versions: list[dict] | None = None

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["locales"] = list(CONCRETE_LOCALES)
        return payload


class Phase4MenuSeedService:
    def __init__(self, uow_factory) -> None:
        self.uow_factory = uow_factory
        self.management = MenuManagementService(uow_factory)

    def seed(self) -> Phase4SeedSummary:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        with self.uow_factory() as uow:
            restaurants = [(restaurant.id, restaurant.code) for restaurant in uow.tenants.list_active_simulation_restaurants()]
        summary = Phase4SeedSummary(restaurants=len(restaurants), published_versions=[])
        for restaurant_id, restaurant_code in restaurants:
            version, stats, idempotent = self.management.publish_phase4_catalog(restaurant_id, catalog)
            if idempotent:
                summary.idempotent_restaurants += 1
            else:
                summary.menu_versions_created += 1
            summary.categories += stats["categories"]
            summary.items += stats["items"]
            summary.aliases += stats["aliases"]
            summary.modifier_options += stats["modifierOptions"]
            summary.published_versions.append(
                {
                    "restaurantCode": restaurant_code,
                    "versionId": version.id,
                    "versionNumber": version.version_number,
                    "idempotent": idempotent,
                }
            )
        return summary
