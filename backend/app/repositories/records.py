from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TenantRecord:
    restaurant_id: int
    restaurant_code: str
    branch_id: int
    branch_code: str
    restaurant_timezone: str
    branch_timezone: str
    currency: str
    is_simulation: bool


@dataclass(frozen=True)
class MenuItemRecord:
    id: int
    menu_version_id: int
    code: str
    name: str
    category: str
    base_price_minor: int
    currency: str
    active: bool
    available: bool
    attributes: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    allergens: list[dict[str, Any]] = field(default_factory=list)
