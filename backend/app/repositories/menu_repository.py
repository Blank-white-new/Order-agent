from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import (
    Allergen,
    Branch,
    BranchItemAvailability,
    MenuCategory,
    MenuCategoryTranslation,
    MenuItem,
    MenuItemAlias,
    MenuItemAllergen,
    MenuItemTranslation,
    MenuItemModifierGroup,
    MenuVersion,
    ModifierGroup,
    ModifierOption,
)
from app.domain.errors import menu_publish_conflict
from app.repositories.records import MenuItemRecord


class MenuRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_version(self, version_id: int) -> MenuVersion | None:
        return self.session.get(MenuVersion, version_id)

    def get_active_version(self, branch_id: int) -> MenuVersion | None:
        branch = self.session.get(Branch, branch_id)
        if not branch or not branch.active_menu_version_id:
            return None
        return self.session.scalar(
            select(MenuVersion).where(
                MenuVersion.id == branch.active_menu_version_id,
                MenuVersion.restaurant_id == branch.restaurant_id,
                MenuVersion.status == "PUBLISHED",
            )
        )

    def list_items(self, branch_id: int, *, locale: str = "zh-CN", include_unavailable: bool = False) -> list[MenuItemRecord]:
        version = self.get_active_version(branch_id)
        if not version:
            return []
        rows = self.session.execute(
            select(MenuItem, MenuCategory)
            .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
            .where(MenuItem.menu_version_id == version.id)
            .order_by(MenuCategory.sort_order, MenuItem.id)
        ).all()
        item_ids = [item.id for item, _category in rows]
        if not item_ids:
            return []

        item_translations = {
            item_id: (name, description)
            for item_id, name, description in self.session.execute(
                select(
                    MenuItemTranslation.menu_item_id,
                    MenuItemTranslation.name,
                    MenuItemTranslation.description,
                ).where(
                    MenuItemTranslation.menu_item_id.in_(item_ids), MenuItemTranslation.locale == locale
                )
            )
        }
        category_ids = list({category.id for _item, category in rows})
        category_names = dict(
            self.session.execute(
                select(MenuCategoryTranslation.category_id, MenuCategoryTranslation.name).where(
                    MenuCategoryTranslation.category_id.in_(category_ids), MenuCategoryTranslation.locale == locale
                )
            ).all()
        )
        aliases: dict[int, list[str]] = {}
        for item_id, alias in self.session.execute(
            select(MenuItemAlias.menu_item_id, MenuItemAlias.alias).where(
                MenuItemAlias.menu_item_id.in_(item_ids), MenuItemAlias.locale == locale
            )
        ):
            aliases.setdefault(item_id, []).append(alias)
        availability = {
            item_id: available
            for item_id, available in self.session.execute(
                select(BranchItemAvailability.menu_item_id, BranchItemAvailability.available).where(
                    BranchItemAvailability.branch_id == branch_id,
                    BranchItemAvailability.menu_item_id.in_(item_ids),
                )
            )
        }
        allergens: dict[int, list[dict]] = {}
        allergen_rows = self.session.execute(
            select(MenuItemAllergen, Allergen)
            .join(Allergen, Allergen.id == MenuItemAllergen.allergen_id)
            .where(MenuItemAllergen.menu_item_id.in_(item_ids))
        ).all()
        for declaration, allergen in allergen_rows:
            allergens.setdefault(declaration.menu_item_id, []).append(
                {
                    "code": allergen.code,
                    "name": allergen.name,
                    "declaration": declaration.declaration,
                    "source": declaration.source,
                    "verifiedAt": declaration.verified_at.isoformat() if declaration.verified_at else None,
                }
            )

        records = []
        for item, category in rows:
            is_available = item.active and availability.get(item.id, True)
            if not include_unavailable and not is_available:
                continue
            attributes = dict(item.attributes_json or {})
            attributes["description"] = item_translations.get(item.id, (item.code, ""))[1]
            records.append(
                MenuItemRecord(
                    id=item.id,
                    menu_version_id=item.menu_version_id,
                    code=item.code,
                    name=item_translations.get(item.id, (item.code, ""))[0],
                    category=category_names.get(category.id, category.code),
                    base_price_minor=item.base_price_minor,
                    currency=item.currency,
                    active=item.active,
                    available=is_available,
                    attributes=attributes,
                    aliases=list(aliases.get(item.id, [])),
                    allergens=list(allergens.get(item.id, [])),
                )
            )
        return records

    def get_item_for_branch(self, branch_id: int, item_id: int) -> MenuItemRecord | None:
        return next((item for item in self.list_items(branch_id, include_unavailable=True) if item.id == item_id), None)

    def get_item_by_code(self, branch_id: int, code: str) -> MenuItemRecord | None:
        return next((item for item in self.list_items(branch_id, include_unavailable=True) if item.code == code), None)

    def modifier_configuration(self, menu_item_id: int) -> list[dict]:
        groups = list(
            self.session.scalars(
                select(ModifierGroup)
                .join(MenuItemModifierGroup, MenuItemModifierGroup.modifier_group_id == ModifierGroup.id)
                .where(MenuItemModifierGroup.menu_item_id == menu_item_id)
                .order_by(MenuItemModifierGroup.sort_order, ModifierGroup.id)
            )
        )
        if not groups:
            return []
        options_by_group: dict[int, list[ModifierOption]] = {group.id: [] for group in groups}
        for option in self.session.scalars(
            select(ModifierOption)
            .where(ModifierOption.modifier_group_id.in_(options_by_group))
            .order_by(ModifierOption.sort_order, ModifierOption.id)
        ):
            options_by_group[option.modifier_group_id].append(option)
        return [
            {
                "id": group.id,
                "code": group.code,
                "name": group.name,
                "required": group.required,
                "minSelections": group.min_selections,
                "maxSelections": group.max_selections,
                "active": group.active,
                "options": [
                    {
                        "id": option.id,
                        "code": option.code,
                        "name": option.name,
                        "priceDeltaMinor": option.price_delta_minor,
                        "active": option.active,
                    }
                    for option in options_by_group[group.id]
                ],
            }
            for group in groups
        ]

    def category_configuration(self, branch_id: int, *, locale: str = "zh-CN") -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
        version = self.get_active_version(branch_id)
        if not version:
            return [], {}, {}
        rows = self.session.execute(
            select(MenuCategory, MenuCategoryTranslation)
            .join(
                MenuCategoryTranslation,
                (MenuCategoryTranslation.category_id == MenuCategory.id) & (MenuCategoryTranslation.locale == locale),
            )
            .where(MenuCategory.menu_version_id == version.id, MenuCategory.active.is_(True))
            .order_by(MenuCategory.sort_order)
        ).all()
        categories = []
        aliases: dict[str, list[str]] = {}
        groups: dict[str, list[str]] = {}
        for category, translation in rows:
            name = translation.name
            categories.append(name)
            metadata = dict(category.metadata_json or {})
            aliases[name] = list(dict.fromkeys([name, *metadata.get("aliases", [])]))
            for group in metadata.get("groups", []):
                groups.setdefault(group, []).append(name)
        return categories, aliases, groups

    def next_version_number(self, restaurant_id: int) -> int:
        numbers = self.session.scalars(select(MenuVersion.version_number).where(MenuVersion.restaurant_id == restaurant_id)).all()
        return max(numbers, default=0) + 1

    def publish_for_restaurant(self, restaurant_id: int, version: MenuVersion) -> None:
        now = datetime.now(timezone.utc)
        current = self.session.scalar(
            select(MenuVersion)
            .where(
                MenuVersion.restaurant_id == restaurant_id,
                MenuVersion.status == "PUBLISHED",
                MenuVersion.id != version.id,
            )
            .with_for_update()
        )
        if current is not None:
            archived = self.session.execute(
                update(MenuVersion)
                .where(MenuVersion.id == current.id, MenuVersion.status == "PUBLISHED")
                .values(status="ARCHIVED")
            )
            if archived.rowcount != 1:
                raise menu_publish_conflict()
        version.status = "PUBLISHED"
        version.published_at = now
        version.effective_at = version.effective_at or now
        self.session.execute(
            update(Branch)
            .where(
                Branch.restaurant_id == restaurant_id,
                Branch.status == "ACTIVE",
                Branch.deleted_at.is_(None),
            )
            .values(active_menu_version_id=version.id)
        )

    def add(self, entity) -> None:
        self.session.add(entity)

    def flush(self) -> None:
        self.session.flush()
