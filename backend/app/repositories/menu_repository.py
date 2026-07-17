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
    ModifierGroupTranslation,
    ModifierOption,
    ModifierOptionTranslation,
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

    def multilingual_lexicon(self, branch_id: int) -> list[dict]:
        """Return only the active version's reviewed names, aliases and modifier codes."""
        version = self.get_active_version(branch_id)
        if not version:
            return []
        items = list(
            self.session.scalars(
                select(MenuItem)
                .where(MenuItem.menu_version_id == version.id, MenuItem.active.is_(True))
                .order_by(MenuItem.id)
            )
        )
        item_ids = [item.id for item in items]
        translations: dict[int, dict[str, str]] = {item.id: {} for item in items}
        aliases: dict[int, dict[str, list[str]]] = {item.id: {} for item in items}
        for item_id, locale, name in self.session.execute(
            select(MenuItemTranslation.menu_item_id, MenuItemTranslation.locale, MenuItemTranslation.name).where(
                MenuItemTranslation.menu_item_id.in_(item_ids)
            )
        ):
            translations[item_id][locale] = name
        for item_id, locale, alias in self.session.execute(
            select(MenuItemAlias.menu_item_id, MenuItemAlias.locale, MenuItemAlias.alias).where(
                MenuItemAlias.menu_item_id.in_(item_ids)
            )
        ):
            aliases[item_id].setdefault(locale, []).append(alias)

        availability = {
            item_id: available
            for item_id, available in self.session.execute(
                select(BranchItemAvailability.menu_item_id, BranchItemAvailability.available).where(
                    BranchItemAvailability.branch_id == branch_id,
                    BranchItemAvailability.menu_item_id.in_(item_ids),
                )
            )
        }
        groups_by_item: dict[int, list[ModifierGroup]] = {item.id: [] for item in items}
        group_rows = self.session.execute(
            select(MenuItemModifierGroup.menu_item_id, ModifierGroup)
            .join(ModifierGroup, ModifierGroup.id == MenuItemModifierGroup.modifier_group_id)
            .where(MenuItemModifierGroup.menu_item_id.in_(item_ids))
            .order_by(MenuItemModifierGroup.sort_order, ModifierGroup.id)
        ).all()
        group_ids: list[int] = []
        for item_id, group in group_rows:
            groups_by_item[item_id].append(group)
            group_ids.append(group.id)

        group_translations: dict[int, dict[str, dict]] = {group_id: {} for group_id in group_ids}
        for row in self.session.scalars(
            select(ModifierGroupTranslation).where(ModifierGroupTranslation.modifier_group_id.in_(group_ids))
        ):
            group_translations[row.modifier_group_id][row.locale] = {
                "name": row.name,
                "aliases": list(row.aliases_json or []),
            }
        options = list(
            self.session.scalars(
                select(ModifierOption)
                .where(ModifierOption.modifier_group_id.in_(group_ids))
                .order_by(ModifierOption.sort_order, ModifierOption.id)
            )
        ) if group_ids else []
        option_translations: dict[int, dict[str, dict]] = {option.id: {} for option in options}
        option_ids = [option.id for option in options]
        if option_ids:
            for row in self.session.scalars(
                select(ModifierOptionTranslation).where(
                    ModifierOptionTranslation.modifier_option_id.in_(option_ids)
                )
            ):
                option_translations[row.modifier_option_id][row.locale] = {
                    "name": row.name,
                    "aliases": list(row.aliases_json or []),
                }
        options_by_group: dict[int, list[ModifierOption]] = {group_id: [] for group_id in group_ids}
        for option in options:
            options_by_group[option.modifier_group_id].append(option)

        return [
            {
                "code": item.code,
                "menuItemId": item.id,
                "menuVersionId": item.menu_version_id,
                "names": translations[item.id],
                "aliases": aliases[item.id],
                "available": bool(availability.get(item.id, True)),
                "modifierGroups": [
                    {
                        "code": group.code,
                        "required": group.required,
                        "minSelections": group.min_selections,
                        "maxSelections": group.max_selections,
                        "active": group.active,
                        "translations": group_translations.get(group.id, {}),
                        "options": [
                            {
                                "groupCode": group.code,
                                "optionCode": option.code,
                                "internalName": option.name,
                                "priceDeltaMinor": option.price_delta_minor,
                                "active": option.active,
                                "translations": option_translations.get(option.id, {}),
                            }
                            for option in options_by_group.get(group.id, [])
                        ],
                    }
                    for group in groups_by_item[item.id]
                ],
            }
            for item in items
        ]

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

    def published_version_for_restaurant(self, restaurant_id: int) -> MenuVersion | None:
        return self.session.scalar(
            select(MenuVersion).where(
                MenuVersion.restaurant_id == restaurant_id,
                MenuVersion.status == "PUBLISHED",
            )
        )

    def is_phase4_catalog_complete(self, version: MenuVersion, catalog_version: str, locales: tuple[str, ...]) -> bool:
        items = list(self.session.scalars(select(MenuItem).where(MenuItem.menu_version_id == version.id)))
        if not items or any((item.attributes_json or {}).get("multilingual_catalog_version") != catalog_version for item in items):
            return False
        item_ids = [item.id for item in items]
        translation_counts = {
            item_id: set()
            for item_id in item_ids
        }
        for item_id, locale in self.session.execute(
            select(MenuItemTranslation.menu_item_id, MenuItemTranslation.locale).where(
                MenuItemTranslation.menu_item_id.in_(item_ids)
            )
        ):
            translation_counts[item_id].add(locale)
        alias_counts = {item_id: set() for item_id in item_ids}
        for item_id, locale in self.session.execute(
            select(MenuItemAlias.menu_item_id, MenuItemAlias.locale).where(MenuItemAlias.menu_item_id.in_(item_ids))
        ):
            alias_counts[item_id].add(locale)
        expected = set(locales)
        if any(translation_counts[item.id] != expected or alias_counts[item.id] != expected for item in items):
            return False
        groups = list(self.session.scalars(select(ModifierGroup).where(ModifierGroup.menu_version_id == version.id)))
        group_ids = [group.id for group in groups]
        group_locales = {group_id: set() for group_id in group_ids}
        for group_id, locale in self.session.execute(
            select(ModifierGroupTranslation.modifier_group_id, ModifierGroupTranslation.locale).where(
                ModifierGroupTranslation.modifier_group_id.in_(group_ids)
            )
        ):
            group_locales[group_id].add(locale)
        options = list(
            self.session.scalars(select(ModifierOption).where(ModifierOption.modifier_group_id.in_(group_ids)))
        ) if group_ids else []
        option_ids = [option.id for option in options]
        option_locales = {option_id: set() for option_id in option_ids}
        if option_ids:
            for option_id, locale in self.session.execute(
                select(ModifierOptionTranslation.modifier_option_id, ModifierOptionTranslation.locale).where(
                    ModifierOptionTranslation.modifier_option_id.in_(option_ids)
                )
            ):
                option_locales[option_id].add(locale)
        return all(group_locales[group_id] == expected for group_id in group_ids) and all(
            option_locales[option_id] == expected for option_id in option_ids
        )

    def clone_phase4_draft(self, restaurant_id: int, source: MenuVersion, catalog: dict) -> tuple[MenuVersion, dict]:
        """Clone immutable published rows into a localized draft inside the caller transaction."""
        version = MenuVersion(
            restaurant_id=restaurant_id,
            version_number=self.next_version_number(restaurant_id),
            status="DRAFT",
        )
        self.add(version)
        self.flush()
        stats = {"categories": 0, "items": 0, "aliases": 0, "modifierOptions": 0}

        categories = list(
            self.session.scalars(
                select(MenuCategory)
                .where(MenuCategory.menu_version_id == source.id)
                .order_by(MenuCategory.sort_order, MenuCategory.id)
            )
        )
        category_map: dict[int, MenuCategory] = {}
        for old in categories:
            new = MenuCategory(
                menu_version_id=version.id,
                code=old.code,
                sort_order=old.sort_order,
                active=old.active,
                metadata_json=dict(old.metadata_json or {}),
            )
            self.add(new)
            self.flush()
            category_map[old.id] = new
            translations = catalog["categories"].get(old.code)
            if not translations:
                raise ValueError(f"missing category translations for {old.code}")
            for locale, data in sorted(translations.items()):
                self.add(MenuCategoryTranslation(category_id=new.id, locale=locale, name=data["name"]))
            stats["categories"] += 1

        old_items = list(
            self.session.scalars(
                select(MenuItem).where(MenuItem.menu_version_id == source.id).order_by(MenuItem.id)
            )
        )
        old_item_ids = [item.id for item in old_items]
        old_aliases: dict[int, list[MenuItemAlias]] = {item_id: [] for item_id in old_item_ids}
        for alias in self.session.scalars(
            select(MenuItemAlias).where(MenuItemAlias.menu_item_id.in_(old_item_ids))
        ):
            old_aliases[alias.menu_item_id].append(alias)
        item_map: dict[int, MenuItem] = {}
        item_by_code: dict[str, MenuItem] = {}
        for old in old_items:
            translations = catalog["items"].get(old.code)
            if not translations:
                raise ValueError(f"missing item translations for {old.code}")
            attributes = dict(old.attributes_json or {})
            attributes["multilingual_catalog_version"] = catalog["catalog_version"]
            new = MenuItem(
                menu_version_id=version.id,
                category_id=category_map[old.category_id].id,
                code=old.code,
                base_price_minor=old.base_price_minor,
                currency=old.currency,
                active=old.active,
                attributes_json=attributes,
            )
            self.add(new)
            self.flush()
            item_map[old.id] = new
            item_by_code[new.code] = new
            alias_values: dict[tuple[str, str], str] = {}
            for alias in old_aliases.get(old.id, []):
                alias_values[(alias.locale, normalize_repository_alias(alias.alias))] = alias.alias
            for locale, data in sorted(translations.items()):
                self.add(
                    MenuItemTranslation(
                        menu_item_id=new.id,
                        locale=locale,
                        name=data["name"],
                        description=data.get("description", ""),
                    )
                )
                for alias in data.get("aliases", []):
                    alias_values[(locale, normalize_repository_alias(alias))] = alias
            for (locale, normalized_alias), alias in sorted(alias_values.items()):
                self.add(
                    MenuItemAlias(
                        menu_item_id=new.id,
                        menu_version_id=version.id,
                        locale=locale,
                        alias=alias,
                        normalized_alias=normalized_alias,
                    )
                )
                stats["aliases"] += 1
            stats["items"] += 1

        declarations = list(
            self.session.scalars(
                select(MenuItemAllergen).where(MenuItemAllergen.menu_version_id == source.id)
            )
        )
        for declaration in declarations:
            self.add(
                MenuItemAllergen(
                    menu_item_id=item_map[declaration.menu_item_id].id,
                    allergen_id=declaration.allergen_id,
                    restaurant_id=restaurant_id,
                    declaration=declaration.declaration,
                    source=declaration.source,
                    verified_at=declaration.verified_at,
                    menu_version_id=version.id,
                )
            )

        old_groups = list(
            self.session.scalars(
                select(ModifierGroup).where(ModifierGroup.menu_version_id == source.id).order_by(ModifierGroup.id)
            )
        )
        group_map: dict[int, ModifierGroup] = {}
        for old in old_groups:
            new = ModifierGroup(
                menu_version_id=version.id,
                code=old.code,
                name=old.name,
                required=old.required,
                min_selections=old.min_selections,
                max_selections=old.max_selections,
                sort_order=old.sort_order,
                active=old.active,
            )
            self.add(new)
            self.flush()
            group_map[old.id] = new
            group_names = {
                "en-HK": ("Options", ["choices"]),
                "yue-Hant-HK": ("選項", ["配搭"]),
                "zh-CN": ("选项", ["可选项"]),
            }
            for locale, (name, aliases) in sorted(group_names.items()):
                self.add(
                    ModifierGroupTranslation(
                        modifier_group_id=new.id,
                        menu_version_id=version.id,
                        locale=locale,
                        name=name,
                        aliases_json=aliases,
                    )
                )

        old_options = list(
            self.session.scalars(
                select(ModifierOption).where(ModifierOption.modifier_group_id.in_(group_map)).order_by(ModifierOption.id)
            )
        ) if group_map else []
        option_map: dict[int, ModifierOption] = {}
        for old in old_options:
            terms = catalog["modifier_terms"].get(old.name)
            if not terms:
                raise ValueError(f"missing modifier translations for {old.name}")
            new = ModifierOption(
                modifier_group_id=group_map[old.modifier_group_id].id,
                code=old.code,
                name=old.name,
                price_delta_minor=old.price_delta_minor,
                sort_order=old.sort_order,
                active=old.active,
            )
            self.add(new)
            self.flush()
            option_map[old.id] = new
            for locale, data in sorted(terms.items()):
                self.add(
                    ModifierOptionTranslation(
                        modifier_option_id=new.id,
                        modifier_group_id=new.modifier_group_id,
                        menu_version_id=version.id,
                        locale=locale,
                        name=data["name"],
                        aliases_json=list(data.get("aliases", [])),
                    )
                )
            stats["modifierOptions"] += 1

        old_links = list(
            self.session.scalars(
                select(MenuItemModifierGroup).where(MenuItemModifierGroup.menu_version_id == source.id)
            )
        )
        for link in old_links:
            self.add(
                MenuItemModifierGroup(
                    menu_item_id=item_map[link.menu_item_id].id,
                    modifier_group_id=group_map[link.modifier_group_id].id,
                    menu_version_id=version.id,
                    sort_order=link.sort_order,
                )
            )

        branches = list(
            self.session.scalars(select(Branch).where(Branch.restaurant_id == restaurant_id, Branch.deleted_at.is_(None)))
        )
        old_by_id = {item.id: item for item in old_items}
        for branch in branches:
            rows = list(
                self.session.scalars(
                    select(BranchItemAvailability).where(
                        BranchItemAvailability.branch_id == branch.id,
                        BranchItemAvailability.menu_version_id == source.id,
                    )
                )
            )
            availability_by_code = {
                old_by_id[row.menu_item_id].code: row for row in rows if row.menu_item_id in old_by_id
            }
            for code, new_item in item_by_code.items():
                old_row = availability_by_code.get(code)
                self.add(
                    BranchItemAvailability(
                        branch_id=branch.id,
                        restaurant_id=restaurant_id,
                        menu_item_id=new_item.id,
                        menu_version_id=version.id,
                        available=old_row.available if old_row else True,
                        sold_out_until=old_row.sold_out_until if old_row else None,
                        reason_code=old_row.reason_code if old_row else None,
                    )
                )
        self.flush()
        return version, stats

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


def normalize_repository_alias(value: str) -> str:
    return "".join(value.casefold().split())
