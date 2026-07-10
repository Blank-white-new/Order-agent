from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.schemas import MenuItem


MENU_CONFIG_ENV_VAR = "MENU_CONFIG_PATH"
SUPPORTED_MENU_CONFIG_VERSION = 1
DEFAULT_MENU_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "menu.json"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

if hasattr(MenuItem, "model_fields"):
    _MENU_ITEM_FIELDS = set(MenuItem.model_fields)
else:
    _MENU_ITEM_FIELDS = set(MenuItem.__fields__)
_LIST_STRING_FIELDS = {"tags", "options", "aliases", "ingredients", "allergens", "taste_profile"}
_STRING_FIELDS = {"id", "name", "category", "description", "recommend_reason", "prep_speed", "portion"}
_NUMERIC_FIELDS = {"recommended_score"}
_INTEGER_FIELDS = {"price", "spicy_level"}


class MenuConfigError(ValueError):
    """Raised when the menu configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class LoadedMenuConfig:
    items: list[MenuItem]
    categories: list[str]
    category_aliases: dict[str, list[str]]
    category_group_aliases: dict[str, list[str]]
    category_groups: dict[str, list[str]]
    safe_match_aliases: dict[str, list[str]]
    currency: str
    source_label: str


def load_menu_config(config_path: str | Path | None = None) -> LoadedMenuConfig:
    path, is_external = _resolve_config_path(config_path)
    source_label = _safe_path_label(path, is_external=is_external)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        source = MENU_CONFIG_ENV_VAR if is_external else "default menu config"
        raise MenuConfigError(f"Menu config file not found for {source}: {source_label}") from exc
    except OSError as exc:
        raise MenuConfigError(f"Menu config file could not be read: {source_label}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MenuConfigError(f"Menu config JSON is invalid at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc

    return parse_menu_config(payload, source_label=source_label)


def parse_menu_config(payload: Any, *, source_label: str = "menu config") -> LoadedMenuConfig:
    if not isinstance(payload, dict):
        raise MenuConfigError("Menu config must be a JSON object.")

    version = payload.get("version", SUPPORTED_MENU_CONFIG_VERSION)
    if version != SUPPORTED_MENU_CONFIG_VERSION:
        raise MenuConfigError(f"Unsupported menu config version: {version!r}.")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise MenuConfigError("Menu config field 'items' must be a non-empty array.")

    categories, category_aliases, category_groups = _parse_categories(payload.get("categories"))
    items = [_parse_item(raw_item, index) for index, raw_item in enumerate(raw_items)]
    if not categories:
        categories = _categories_from_items(items)
        category_aliases = {category: [category] for category in categories}
    _validate_item_categories(items, categories)

    category_group_aliases = _parse_string_list_mapping(
        payload.get("category_group_aliases", {}),
        field_name="category_group_aliases",
        allow_empty=True,
    )
    safe_match_aliases = _parse_string_list_mapping(
        payload.get("safe_match_aliases", {}),
        field_name="safe_match_aliases",
        allow_empty=True,
    )
    _validate_safe_match_aliases(safe_match_aliases, {item.id for item in items})
    _validate_unique_match_names(items, safe_match_aliases)

    currency = payload.get("currency", "CNY")
    if not _is_non_empty_string(currency):
        raise MenuConfigError("Menu config field 'currency' must be a non-empty string when provided.")

    return LoadedMenuConfig(
        items=items,
        categories=categories,
        category_aliases=category_aliases,
        category_group_aliases=category_group_aliases,
        category_groups=category_groups,
        safe_match_aliases=safe_match_aliases,
        currency=currency.strip(),
        source_label=source_label,
    )


def _resolve_config_path(config_path: str | Path | None) -> tuple[Path, bool]:
    configured = str(config_path).strip() if config_path is not None else (os.getenv(MENU_CONFIG_ENV_VAR) or "").strip()
    if configured:
        return Path(configured).expanduser(), True
    return DEFAULT_MENU_CONFIG_PATH, False


def _parse_categories(raw_categories: Any) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    if raw_categories is None:
        return [], {}, {}
    if not isinstance(raw_categories, list):
        raise MenuConfigError("Menu config field 'categories' must be an array when provided.")

    categories: list[str] = []
    aliases_by_category: dict[str, list[str]] = {}
    groups_by_group: dict[str, list[str]] = {}
    seen: set[str] = set()
    for index, raw_category in enumerate(raw_categories):
        if isinstance(raw_category, str):
            name = _require_text(raw_category, f"categories[{index}]")
            aliases = [name]
            groups: list[str] = []
        elif isinstance(raw_category, dict):
            name = _require_text(raw_category.get("name"), f"categories[{index}].name")
            aliases = _optional_string_list(raw_category.get("aliases", []), f"categories[{index}].aliases")
            groups = _optional_string_list(raw_category.get("groups", []), f"categories[{index}].groups")
            aliases = _dedupe([name, *aliases])
        else:
            raise MenuConfigError(f"Menu config field 'categories[{index}]' must be a string or object.")

        if name in seen:
            raise MenuConfigError(f"Duplicate category name: {name}.")
        seen.add(name)
        categories.append(name)
        aliases_by_category[name] = aliases
        for group in groups:
            groups_by_group.setdefault(group, []).append(name)
    return categories, aliases_by_category, groups_by_group


def _parse_item(raw_item: Any, index: int) -> MenuItem:
    if not isinstance(raw_item, dict):
        raise MenuConfigError(f"Menu item at index {index} must be an object.")
    unknown_fields = set(raw_item) - _MENU_ITEM_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise MenuConfigError(f"Menu item at index {index} has unsupported field(s): {names}.")

    item_data: dict[str, Any] = {}
    for field in ["id", "name", "category", "price"]:
        if field not in raw_item:
            raise MenuConfigError(f"Menu item at index {index} is missing required field '{field}'.")

    for field in _STRING_FIELDS:
        if field in raw_item:
            item_data[field] = _require_text(raw_item[field], f"items[{index}].{field}")
    for field in _LIST_STRING_FIELDS:
        if field in raw_item:
            item_data[field] = _optional_string_list(raw_item[field], f"items[{index}].{field}")
    for field in _INTEGER_FIELDS:
        if field in raw_item:
            item_data[field] = _require_non_negative_int(raw_item[field], f"items[{index}].{field}")
    for field in _NUMERIC_FIELDS:
        if field in raw_item:
            item_data[field] = _require_number(raw_item[field], f"items[{index}].{field}")
    if "available" in raw_item:
        if not isinstance(raw_item["available"], bool):
            raise MenuConfigError(f"Menu item field 'items[{index}].available' must be a boolean.")
        item_data["available"] = raw_item["available"]

    try:
        return MenuItem(**item_data)
    except Exception as exc:
        raise MenuConfigError(f"Menu item at index {index} failed schema validation.") from exc


def _parse_string_list_mapping(raw_mapping: Any, *, field_name: str, allow_empty: bool) -> dict[str, list[str]]:
    if raw_mapping is None and allow_empty:
        return {}
    if not isinstance(raw_mapping, dict):
        raise MenuConfigError(f"Menu config field '{field_name}' must be an object.")
    parsed: dict[str, list[str]] = {}
    for raw_key, raw_values in raw_mapping.items():
        key = _require_text(raw_key, f"{field_name} key")
        parsed[key] = _optional_string_list(raw_values, f"{field_name}.{key}")
    return parsed


def _validate_item_categories(items: list[MenuItem], categories: list[str]) -> None:
    known_categories = set(categories)
    for item in items:
        if item.category not in known_categories:
            raise MenuConfigError(f"Menu item '{item.id}' uses unknown category '{item.category}'.")


def _validate_safe_match_aliases(safe_match_aliases: dict[str, list[str]], item_ids: set[str]) -> None:
    for item_id in safe_match_aliases:
        if item_id not in item_ids:
            raise MenuConfigError(f"safe_match_aliases references unknown item id '{item_id}'.")


def _validate_unique_match_names(items: list[MenuItem], safe_match_aliases: dict[str, list[str]]) -> None:
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_match_names: dict[str, str] = {}
    for item in items:
        if item.id in seen_ids:
            raise MenuConfigError(f"Duplicate menu item id: {item.id}.")
        seen_ids.add(item.id)
        if item.name in seen_names:
            raise MenuConfigError(f"Duplicate menu item name: {item.name}.")
        seen_names.add(item.name)

        names = [item.name, *item.aliases, *safe_match_aliases.get(item.id, [])]
        for name in names:
            owner = seen_match_names.get(name)
            if owner is not None:
                raise MenuConfigError(f"Menu match alias/name '{name}' conflicts between '{owner}' and '{item.id}'.")
            seen_match_names[name] = item.id


def _categories_from_items(items: list[MenuItem]) -> list[str]:
    categories: list[str] = []
    for item in items:
        if item.category not in categories:
            categories.append(item.category)
    return categories


def _optional_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise MenuConfigError(f"Menu config field '{field_name}' must be an array of strings.")
    entries: list[str] = []
    for index, raw_entry in enumerate(value):
        entry = _require_text(raw_entry, f"{field_name}[{index}]")
        entries.append(entry)
    return _dedupe(entries)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MenuConfigError(f"Menu config field '{field_name}' must be a non-empty string.")
    return value.strip()


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MenuConfigError(f"Menu config field '{field_name}' must be a non-negative integer.")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise MenuConfigError(f"Menu config field '{field_name}' must be a finite number.")
    return float(value)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _safe_path_label(path: Path, *, is_external: bool) -> str:
    if is_external:
        if path.is_absolute():
            return f"{path.name or 'configured file'} via {MENU_CONFIG_ENV_VAR}"
        return str(path)
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name
