from __future__ import annotations

from collections import Counter
from typing import Any

from app.domain.errors import (
    modifier_ambiguous,
    modifier_duplicate,
    modifier_not_available,
    modifier_required,
    modifier_too_few,
    modifier_too_many,
)


class ModifierSelectionValidator:
    """Resolve legacy names or structured codes and enforce authoritative group rules."""

    def validate(self, menu_repository, menu_item_id: int, selections: list[Any]) -> list[dict]:
        groups = menu_repository.modifier_configuration(menu_item_id)
        resolved: list[tuple[dict, dict]] = []
        for selection in selections:
            resolved.append(self._resolve(groups, selection))

        option_ids = [option["id"] for _group, option in resolved]
        if len(option_ids) != len(set(option_ids)):
            raise modifier_duplicate()

        counts = Counter(group["id"] for group, _option in resolved)
        for group in groups:
            if not group["active"]:
                continue
            count = counts[group["id"]]
            minimum = max(group["minSelections"], 1 if group["required"] else 0)
            if count == 0 and group["required"]:
                raise modifier_required(group["code"])
            if count < minimum:
                raise modifier_too_few(group["code"])
            if count > group["maxSelections"]:
                raise modifier_too_many(group["code"])

        return [
            {
                "groupCode": group["code"],
                "optionCode": option["code"],
                "name": option["name"],
                "priceDeltaMinor": option["priceDeltaMinor"],
            }
            for group, option in resolved
        ]

    def _resolve(self, groups: list[dict], selection: Any) -> tuple[dict, dict]:
        if isinstance(selection, dict):
            group_code = selection.get("groupCode")
            option_code = selection.get("optionCode")
            candidates = [
                (group, option)
                for group in groups
                for option in group["options"]
                if group["code"] == group_code and option["code"] == option_code
            ]
        elif isinstance(selection, str):
            candidates = [
                (group, option)
                for group in groups
                for option in group["options"]
                if option["name"] == selection
            ]
        else:
            raise modifier_not_available()

        if not candidates:
            raise modifier_not_available()
        if len(candidates) != 1:
            raise modifier_ambiguous()
        group, option = candidates[0]
        if not group["active"] or not option["active"]:
            raise modifier_not_available()
        return group, option
