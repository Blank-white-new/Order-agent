from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone

from app.db.models import (
    Allergen,
    Branch,
    BranchItemAvailability,
    DeliveryZone,
    MenuCategory,
    MenuCategoryTranslation,
    MenuItem,
    MenuItemAlias,
    MenuItemAllergen,
    MenuItemModifierGroup,
    MenuItemTranslation,
    MenuVersion,
    ModifierGroup,
    ModifierOption,
    OpeningHours,
    Restaurant,
)
from app.services.menu_config_loader import LoadedMenuConfig, load_menu_config


@dataclass
class SeedSummary:
    restaurants_created: int = 0
    branches_created: int = 0
    menu_versions_created: int = 0
    menu_items_created: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


TENANT_SPECS = (
    {
        "code": "hk-sim-restaurant-a",
        "name": "Synthetic Restaurant Alpha",
        "branches": (("central", "Synthetic Branch Central", 500), ("east", "Synthetic Branch East", 650)),
        "price_offset_minor": 0,
        "sold_out_branch": "east",
        "sold_out_index": 0,
    },
    {
        "code": "hk-sim-restaurant-b",
        "name": "Synthetic Restaurant Beta",
        "branches": (("harbor", "Synthetic Branch Harbor", 800), ("north", "Synthetic Branch North", 950)),
        "price_offset_minor": 200,
        "sold_out_branch": "harbor",
        "sold_out_index": 1,
    },
)


def seed_phase2_simulation_data(uow_factory, config: LoadedMenuConfig | None = None) -> SeedSummary:
    config = config or load_menu_config()
    summary = SeedSummary()
    for spec in TENANT_SPECS:
        with uow_factory() as uow:
            if uow.tenants.get_restaurant_by_code(spec["code"]):
                continue
            restaurant = Restaurant(
                code=spec["code"],
                name=spec["name"],
                status="ACTIVE",
                default_locale="zh-CN",
                timezone="Asia/Hong_Kong",
                currency="HKD",
                is_simulation=True,
            )
            uow.menus.add(restaurant)
            uow.flush()
            summary.restaurants_created += 1

            version = MenuVersion(
                restaurant_id=restaurant.id,
                version_number=1,
                status="PUBLISHED",
                effective_at=datetime.now(timezone.utc),
                published_at=datetime.now(timezone.utc),
            )
            uow.menus.add(version)
            uow.flush()
            summary.menu_versions_created += 1

            branches: dict[str, Branch] = {}
            for branch_code, branch_name, _fee in spec["branches"]:
                branch = Branch(
                    restaurant_id=restaurant.id,
                    code=branch_code,
                    name=branch_name,
                    timezone="Asia/Hong_Kong",
                    status="ACTIVE",
                    active_menu_version_id=version.id,
                )
                uow.menus.add(branch)
                branches[branch_code] = branch
            uow.flush()
            summary.branches_created += len(branches)

            categories: dict[str, MenuCategory] = {}
            for index, category_name in enumerate(config.categories):
                groups = [group for group, names in config.category_groups.items() if category_name in names]
                category = MenuCategory(
                    menu_version_id=version.id,
                    code=f"category-{index + 1}",
                    sort_order=index,
                    active=True,
                    metadata_json={
                        "aliases": list(config.category_aliases.get(category_name, [category_name])),
                        "groups": groups,
                    },
                )
                uow.menus.add(category)
                uow.flush()
                uow.menus.add(MenuCategoryTranslation(category_id=category.id, locale="zh-CN", name=category_name))
                categories[category_name] = category

            allergens: dict[str, Allergen] = {}
            for allergen_name in sorted({name for item in config.items for name in item.allergens}):
                code = "allergen-" + hashlib.sha256(allergen_name.encode("utf-8")).hexdigest()[:10]
                allergen = Allergen(restaurant_id=restaurant.id, code=code, name=allergen_name)
                uow.menus.add(allergen)
                allergens[allergen_name] = allergen
            uow.flush()

            menu_items: list[MenuItem] = []
            for item_index, source_item in enumerate(config.items):
                attributes = {
                    "tags": list(source_item.tags),
                    "spicy_level": source_item.spicy_level,
                    "options": list(source_item.options),
                    "ingredients": list(source_item.ingredients),
                    "recommended_score": source_item.recommended_score,
                    "recommend_reason": source_item.recommend_reason,
                    "prep_speed": source_item.prep_speed,
                    "taste_profile": list(source_item.taste_profile),
                    "portion": source_item.portion,
                }
                item = MenuItem(
                    menu_version_id=version.id,
                    category_id=categories[source_item.category].id,
                    code=source_item.id,
                    base_price_minor=source_item.price * 100 + int(spec["price_offset_minor"]),
                    currency="HKD",
                    active=source_item.available,
                    attributes_json=attributes,
                )
                uow.menus.add(item)
                uow.flush()
                menu_items.append(item)
                summary.menu_items_created += 1
                uow.menus.add(
                    MenuItemTranslation(
                        menu_item_id=item.id,
                        locale="zh-CN",
                        name=source_item.name,
                        description=source_item.description,
                    )
                )
                aliases = list(dict.fromkeys([*source_item.aliases, *config.safe_match_aliases.get(source_item.id, [])]))
                for alias in aliases:
                    uow.menus.add(
                        MenuItemAlias(
                            menu_item_id=item.id,
                            menu_version_id=version.id,
                            locale="zh-CN",
                            alias=alias,
                            normalized_alias=_normalize_alias(alias),
                        )
                    )
                for allergen_name in source_item.allergens:
                    uow.menus.add(
                        MenuItemAllergen(
                            menu_item_id=item.id,
                            allergen_id=allergens[allergen_name].id,
                            restaurant_id=restaurant.id,
                            declaration="CONTAINS",
                            source="synthetic-menu-import",
                            verified_at=datetime.now(timezone.utc),
                            menu_version_id=version.id,
                        )
                    )
                if source_item.options:
                    group = ModifierGroup(
                        menu_version_id=version.id,
                        code=f"{source_item.id}-options",
                        name=f"{source_item.name} synthetic options",
                        required=False,
                        min_selections=0,
                        max_selections=max(1, len(source_item.options)),
                        sort_order=0,
                        active=True,
                    )
                    uow.menus.add(group)
                    uow.flush()
                    uow.menus.add(
                        MenuItemModifierGroup(
                            menu_item_id=item.id,
                            modifier_group_id=group.id,
                            menu_version_id=version.id,
                            sort_order=0,
                        )
                    )
                    for option_index, option_name in enumerate(source_item.options):
                        uow.menus.add(
                            ModifierOption(
                                modifier_group_id=group.id,
                                code=f"option-{option_index + 1}",
                                name=option_name,
                                price_delta_minor=0,
                                sort_order=option_index,
                                active=True,
                            )
                        )

            for branch_code, branch_name, fee_minor in spec["branches"]:
                branch = branches[branch_code]
                uow.menus.add(
                    DeliveryZone(
                        branch_id=branch.id,
                        code="synthetic-zone-1",
                        name=f"{branch_name} Synthetic Zone",
                        active=True,
                        fee_minor=fee_minor,
                        minimum_order_minor=0,
                        metadata_json={"synthetic": True},
                    )
                )
                for weekday in range(7):
                    uow.menus.add(
                        OpeningHours(
                            branch_id=branch.id,
                            weekday=weekday,
                            start_time=time(8, 0),
                            end_time=time(22, 0),
                            is_closed=False,
                            metadata_json={"synthetic": True},
                        )
                    )
                for item_index, item in enumerate(menu_items):
                    sold_out = branch_code == spec["sold_out_branch"] and item_index == spec["sold_out_index"]
                    uow.menus.add(
                        BranchItemAvailability(
                            branch_id=branch.id,
                            restaurant_id=restaurant.id,
                            menu_item_id=item.id,
                            menu_version_id=version.id,
                            available=not sold_out,
                            reason_code="SYNTHETIC_SOLD_OUT" if sold_out else None,
                        )
                    )
    return summary


def _normalize_alias(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
