from __future__ import annotations

from pathlib import Path

from app.models.schemas import MenuItem, dump_model
from app.services.menu_config_loader import load_menu_config


class MenuService:
    def __init__(self, config_path: str | Path | None = None) -> None:
        config = load_menu_config(config_path)
        self._items = list(config.items)
        self._categories = list(config.categories)
        self._category_aliases = {category: list(aliases) for category, aliases in config.category_aliases.items()}
        self._category_group_aliases = {group: list(aliases) for group, aliases in config.category_group_aliases.items()}
        self._category_groups = {group: list(categories) for group, categories in config.category_groups.items()}
        self._safe_match_aliases = {item_id: list(aliases) for item_id, aliases in config.safe_match_aliases.items()}

    def get_all_categories(self) -> list[str]:
        categories: list[str] = []
        for category in self._categories:
            if category not in categories and any(item.available and item.category == category for item in self._items):
                categories.append(category)
        for item in self._available_items():
            if item.category not in categories:
                categories.append(item.category)
        return categories

    def get_menu_overview(self, exclude_category: str | None = None) -> dict[str, list[MenuItem]]:
        overview: dict[str, list[MenuItem]] = {}
        for item in self._items:
            if not item.available:
                continue
            if exclude_category and item.category == exclude_category:
                continue
            overview.setdefault(item.category, []).append(item)
        return overview

    def get_items_by_category(self, category: str) -> list[MenuItem]:
        return self.get_available_items_by_category(category)

    def get_available_items_by_category(self, category: str) -> list[MenuItem]:
        resolved = self.find_category_by_alias(category) or category
        return [item for item in self._available_items() if item.category == resolved]

    def find_category_group_by_alias(self, text: str | None) -> str | None:
        if not text:
            return None
        for group, aliases in self._category_group_aliases.items():
            if any(alias in text for alias in aliases):
                return group
        return None

    def get_categories_by_group(self, group: str) -> list[str]:
        resolved = self._resolve_category_group(group) or group
        return list(self._category_groups.get(resolved, []))

    def get_items_by_category_group(self, group: str) -> list[MenuItem]:
        categories = self.get_categories_by_group(group)
        return [item for item in self._available_items() if item.category in categories]

    def find_item_by_name(self, text: str | None) -> MenuItem | None:
        if not text:
            return None
        for item in self._available_items():
            names = self._matching_names(item)
            if any(name and name == text for name in names):
                return item
        matches: list[tuple[int, int, MenuItem]] = []
        for item in self._available_items():
            names = self._matching_names(item)
            for name in names:
                if name and name in text:
                    matches.append((text.find(name), -len(name), item))
        if matches:
            return sorted(matches, key=lambda match: (match[0], match[1]))[0][2]
        return None

    def find_items_in_text(self, text: str | None) -> list[MenuItem]:
        if not text:
            return []
        matches: list[MenuItem] = []
        positions: list[tuple[int, int, MenuItem]] = []
        for item in self._available_items():
            names = self._matching_names(item)
            found = [(text.find(name), len(name)) for name in names if name and name in text]
            if found:
                position, length = min(found, key=lambda pair: (pair[0], -pair[1]))
                positions.append((position, length, item))
        occupied: list[range] = []
        for position, length, item in sorted(positions, key=lambda pair: (pair[0], -pair[1])):
            span = range(position, position + length)
            if any(position < existing.stop and position + length > existing.start for existing in occupied):
                continue
            if item.id not in {existing.id for existing in matches}:
                matches.append(item)
                occupied.append(span)
        return matches

    def find_category_by_alias(self, text: str | None) -> str | None:
        if not text:
            return None
        for category, values in self._category_aliases.items():
            if any(alias in text for alias in values):
                return category
        return None

    def find_items_by_tags(
        self,
        include: list[str] | None = None,
        avoid: list[str] | None = None,
        category: str | None = None,
    ) -> list[MenuItem]:
        include = include or []
        avoid = avoid or []
        items = self._available_items()
        if category:
            resolved = self.find_category_by_alias(category) or category
            items = [item for item in items if item.category == resolved]
        if include:
            items = [item for item in items if any(token in item.name or token in item.tags or token in item.ingredients for token in include)]
        if avoid:
            items = [
                item
                for item in items
                if all(token not in item.name and token not in item.tags and token not in item.ingredients for token in avoid)
            ]
        return items

    def find_similar_items(self, preferences: dict | None = None, limit: int = 3) -> list[MenuItem]:
        preferences = preferences or {}
        category = preferences.get("category")
        avoid = preferences.get("avoid", [])
        include: list[str] = []
        options = preferences.get("options", [])
        if "清淡" in options or "清淡点" in options:
            include.append("清淡")
        if "快" in options or "快一点" in options:
            include.append("快")
        candidates = self.find_items_by_tags(include=include, avoid=avoid, category=category)
        if not category:
            candidates = [item for item in candidates if item.category != "饮品"]
        if any(option in {"不辣", "不要辣"} for option in options):
            candidates = [item for item in candidates if item.spicy_level == 0 or "不辣" in item.options]
        budget = preferences.get("budget")
        if budget:
            candidates = [item for item in candidates if item.price <= int(budget)]
        ordered = sorted(candidates, key=lambda item: (-item.recommended_score, item.price))
        return ordered[:limit]

    def get_ranked_recommendations(
        self,
        category: str | None = None,
        categories: list[str] | None = None,
        preferences: dict | None = None,
        limit: int = 3,
    ) -> list[MenuItem]:
        preferences = preferences or {}
        avoid = preferences.get("avoid", [])
        options = preferences.get("options", [])
        items = self._available_items()
        if category:
            resolved = self.find_category_by_alias(category) or category
            items = [item for item in items if item.category == resolved]
        if categories:
            items = [item for item in items if item.category in categories]
        if avoid:
            items = [
                item
                for item in items
                if all(token not in item.name and token not in item.tags and token not in item.ingredients for token in avoid)
            ]
        if any(option in {"不辣", "不要辣"} for option in options):
            items = [item for item in items if item.spicy_level == 0 or "不辣" in item.options]
        if "清淡" in options:
            items = [item for item in items if "清淡" in item.tags or "清淡" in item.taste_profile or item.spicy_level == 0]
        if "快" in options:
            items = [item for item in items if item.prep_speed == "fast"]
        if budget := preferences.get("budget"):
            items = [item for item in items if item.price <= int(budget)]
        return sorted(items, key=lambda item: (-item.recommended_score, item.price))[:limit]

    def get_items_under_budget(self, budget: int) -> list[MenuItem]:
        return [item for item in self._available_items() if item.price <= budget]

    def get_item_price(self, name: str) -> int | None:
        item = self.find_item_by_name(name)
        return item.price if item else None

    def get_item_options(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return item.options if item else []

    def supports_option(self, name: str, option: str) -> bool:
        item = self.find_item_by_name(name)
        return bool(item and option in item.options)

    def get_ingredients(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return item.ingredients if item else []

    def get_allergen_warnings(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return item.allergens if item else []

    def all_items_as_dicts(self, include_unavailable: bool = False) -> list[dict]:
        items = self._items if include_unavailable else self._available_items()
        return [dump_model(item) for item in items]

    def matching_names_for_item(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return self._matching_names(item) if item else []

    def _matching_names(self, item: MenuItem) -> list[str]:
        return [item.name, *item.aliases, *self._safe_match_aliases.get(item.id, [])]

    def _available_items(self) -> list[MenuItem]:
        return [item for item in self._items if item.available]

    def _resolve_category_group(self, group: str | None) -> str | None:
        if not group:
            return None
        for canonical, aliases in self._category_group_aliases.items():
            if group == canonical or group in aliases:
                return canonical
        return None
