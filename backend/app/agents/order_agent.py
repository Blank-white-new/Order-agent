from __future__ import annotations

from app.models.schemas import Interpretation
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.state.session_state import SessionState


class OrderAgent:
    name = "OrderAgent"

    def __init__(self, menu_service: MenuService, order_service: OrderService) -> None:
        self.menu_service = menu_service
        self.order_service = order_service

    # Pending types that should be cleared when user makes a new order action
    _STALE_PENDING_TYPES = {"confirm_clear_order", "select_ambiguous_dish_candidate"}

    def _is_stale_pending(self, state: SessionState) -> bool:
        """Check if the current pending_action is stale and should be cleared."""
        return bool(state.pending_action and state.pending_action.get("type") in self._STALE_PENDING_TYPES)

    def _order_state_for_restart(self, state: SessionState) -> tuple[SessionState, bool]:
        """Return a working state with old order cleared when restarting."""
        if state.pending_action and state.pending_action.get("type") == "confirm_clear_order":
            working_state = state.clone()
            working_state.current_order = []
            return working_state, True
        return state, False

    def _clear_stale_pending_in_patch(self, state: SessionState, patch: dict) -> None:
        """Add pending_action=None to patch if current pending is stale."""
        if self._is_stale_pending(state):
            patch["pending_action"] = None

    def handle(self, interpretation: Interpretation, state: SessionState) -> dict:
        handlers = {
            "order_food": self._order_food,
            "order_multiple_items": self._order_multiple_items,
            "order_category_items": self._order_category_items,
            "order_category_group_items": self._order_category_group_items,
            "repeat_last_item": self._repeat_last_item,
            "select_recommendation": self._select_recommendation,
            "order_by_preference": self._order_by_preference,
            "update_item_option": self._update_item_option,
            "update_item_quantity": self._update_item_quantity,
            "remove_item": self._remove_item,
            "remove_category_items": self._remove_category_items,
            "replace_item": self._replace_item,
            "clear_order": self._clear_order,
            "modify_order": self._update_item_option,
        }
        handler = handlers.get(interpretation.intent)
        if not handler:
            return {"agent": self.name, "handler": interpretation.intent, "message": "这个订单操作我还需要再确认一下。", "patch": {}}
        return handler(interpretation, state)

    def _order_food(self, interpretation: Interpretation, state: SessionState) -> dict:
        item_name = interpretation.entities.get("item_name")
        item = self.menu_service.find_item_by_name(item_name)
        if not item:
            return {"agent": self.name, "handler": "order_food", "message": "菜单里暂时没找到这个菜。", "patch": {}}
        options = self._supported_options(item.name, interpretation.preferences.get("options", []))
        modifiers = self._modifiers_from_preferences(interpretation.preferences)
        quantity = interpretation.entities.get("quantity", 1)
        order_state, is_restart = self._order_state_for_restart(state)
        order = self.order_service.add_item(
            order_state,
            item,
            quantity=quantity,
            options=options,
            unit=interpretation.entities.get("unit"),
            notes=modifiers.get("note"),
            spicy_level=modifiers.get("spicy_level"),
            exclusions=modifiers.get("exclusions"),
            source="order_food",
        )
        patch = {"current_order": order, "stage": "ordering", "last_mentioned_item": item.name}
        self._clear_stale_pending_in_patch(state, patch)
        detail_text = self._item_detail_text(options, modifiers)
        if is_restart:
            message = f"已重新开始点餐，帮你加入{item.name}{detail_text}。"
        else:
            message = f"已加入{item.name}{detail_text}。"
        return {
            "agent": self.name,
            "handler": "order_food",
            "message": message,
            "patch": patch,
        }

    def _order_multiple_items(self, interpretation: Interpretation, state: SessionState) -> dict:
        specs = []
        names = []
        for spec in interpretation.entities.get("items", []):
            item = self.menu_service.find_item_by_name(spec.get("item_name"))
            if not item:
                continue
            options = self._supported_options(item.name, spec.get("options", []))
            modifiers = self._modifiers_from_spec(spec)
            specs.append(
                {
                    "item": item,
                    "quantity": spec.get("quantity", 1),
                    "options": options,
                    "unit": spec.get("unit"),
                    "notes": modifiers.get("note"),
                    "spicy_level": modifiers.get("spicy_level"),
                    "exclusions": modifiers.get("exclusions"),
                    "source": "order_multiple_items",
                }
            )
            names.append(f"{item.name}{self._item_detail_text(options, modifiers)}")
        if not specs:
            return {"agent": self.name, "handler": "order_multiple_items", "message": "菜单里暂时没找到这些菜。", "patch": {}}
        order_state, is_restart = self._order_state_for_restart(state)
        order = self.order_service.add_items(order_state, specs)
        patch = {"current_order": order, "stage": "ordering", "last_mentioned_item": names[-1].split("（")[0]}
        self._clear_stale_pending_in_patch(state, patch)
        if is_restart:
            message = "已重新开始点餐，帮你加入：" + "、".join(names) + "。"
        else:
            message = "已加入：" + "、".join(names) + "。"
        return {
            "agent": self.name,
            "handler": "order_multiple_items",
            "message": message,
            "patch": patch,
        }

    def _order_category_items(self, interpretation: Interpretation, state: SessionState) -> dict:
        category = interpretation.entities.get("category")
        quantity_each = interpretation.entities.get("quantity_each", 1)
        items = self.menu_service.get_available_items_by_category(category)
        if not items:
            return {"agent": self.name, "handler": "order_category_items", "message": f"目前没有{category}。", "patch": {}}
        if len(items) > 3:
            pending_action = {
                "type": "confirm_order_category_items",
                "category": category,
                "quantity_each": quantity_each,
                "item_names": [item.name for item in items],
            }
            return {
                "agent": self.name,
                "handler": "order_category_items",
                "message": f"{category}有{len(items)}种，确认要各来{quantity_each}份吗？",
                "patch": {"pending_action": pending_action, "last_mentioned_category": category},
            }
        order_state, _ = self._order_state_for_restart(state)
        specs = [{"item": item, "quantity": quantity_each, "unit": interpretation.entities.get("unit"), "source": "order_category_items"} for item in items]
        order = self.order_service.add_items(order_state, specs)
        names = "、".join(item.name for item in items)
        patch = {"current_order": order, "stage": "ordering", "last_mentioned_category": category}
        self._clear_stale_pending_in_patch(state, patch)
        return {
            "agent": self.name,
            "handler": "order_category_items",
            "message": f"好的，{category}我给你各加 {quantity_each} 份：{names}。配送还是自取？",
            "patch": patch,
        }

    def _order_category_group_items(self, interpretation: Interpretation, state: SessionState) -> dict:
        group = interpretation.entities.get("category_group")
        categories = interpretation.entities.get("categories") or self.menu_service.get_categories_by_group(group)
        quantity_each = interpretation.entities.get("quantity_each", 1)
        items = []
        for category in categories:
            items.extend(self.menu_service.get_available_items_by_category(category))
        if not items:
            return {"agent": self.name, "handler": "order_category_group_items", "message": f"目前没有{group}。", "patch": {}}
        pending_action = {
            "type": "confirm_order_category_items",
            "category_group": group,
            "categories": categories,
            "quantity_each": quantity_each,
            "item_names": [item.name for item in items],
        }
        return {
            "agent": self.name,
            "handler": "order_category_group_items",
            "message": f"{group}包含{len(items)}种，确认要各来{quantity_each}份吗？",
            "patch": {"pending_action": pending_action, "last_mentioned_category": group},
        }

    def _select_recommendation(self, interpretation: Interpretation, state: SessionState) -> dict:
        if not state.last_recommendations:
            return {
                "agent": self.name,
                "handler": "select_recommendation",
                "message": "我还没有给你推荐过菜，先给你推荐几个吧。",
                "patch": {},
            }
        index = interpretation.entities.get("index")
        if index is None:
            index = 0
        if index >= len(state.last_recommendations):
            index = 0
        selected = state.last_recommendations[index]
        item = self.menu_service.find_item_by_name(selected["name"])
        options = self._supported_options(item.name, interpretation.preferences.get("options", []))
        modifiers = self._modifiers_from_preferences(interpretation.preferences)
        order_state, is_restart = self._order_state_for_restart(state)
        order = self.order_service.add_item(
            order_state,
            item,
            quantity=1,
            options=options,
            notes=modifiers.get("note"),
            spicy_level=modifiers.get("spicy_level"),
            exclusions=modifiers.get("exclusions"),
            source="select_recommendation",
        )
        patch = {"current_order": order, "stage": "ordering", "last_mentioned_item": item.name}
        self._clear_stale_pending_in_patch(state, patch)
        detail_text = self._item_detail_text(options, modifiers)
        if is_restart:
            message = f"已重新开始点餐，帮你加入{item.name}{detail_text}。"
        else:
            message = f"已加入{item.name}{detail_text}。"
        return {
            "agent": self.name,
            "handler": "select_recommendation",
            "message": message,
            "patch": patch,
        }

    def _order_by_preference(self, interpretation: Interpretation, state: SessionState) -> dict:
        items = self.menu_service.find_similar_items(interpretation.preferences, limit=1)
        if not items:
            return {"agent": self.name, "handler": "order_by_preference", "message": "暂时没找到符合偏好的菜。", "patch": {}}
        order_state, _ = self._order_state_for_restart(state)
        item = items[0]
        order = self.order_service.add_item(order_state, item, quantity=1, source="order_by_preference")
        patch = {"current_order": order, "last_mentioned_item": item.name}
        self._clear_stale_pending_in_patch(state, patch)
        return {
            "agent": self.name,
            "handler": "order_by_preference",
            "message": f"按你的偏好加入{item.name}。",
            "patch": patch,
        }

    def _repeat_last_item(self, interpretation: Interpretation, state: SessionState) -> dict:
        if not state.current_order:
            return {
                "agent": self.name,
                "handler": "repeat_last_item",
                "message": "要再来哪一道菜？你可以直接说菜名。",
                "patch": {},
            }
        index = self._target_order_index(state)
        item_name = state.current_order[index].name
        quantity = interpretation.entities.get("quantity", 1)
        order, updated = self.order_service.adjust_quantity(state, item_name, quantity, index=index)
        patch_data = {}
        if updated:
            patch_data = {"current_order": order, "last_mentioned_item": item_name}
            self._clear_stale_pending_in_patch(state, patch_data)
        return {
            "agent": self.name,
            "handler": "repeat_last_item",
            "message": f"已给{item_name}再加 {quantity} 份。" if updated else "没找到要追加的菜。",
            "patch": patch_data,
        }

    def _update_item_option(self, interpretation: Interpretation, state: SessionState) -> dict:
        options = interpretation.preferences.get("options", [])
        modifiers = self._modifiers_from_preferences(interpretation.preferences)
        item_name = interpretation.entities.get("item_name") or (state.current_order[-1].name if state.current_order else "")
        index = interpretation.entities.get("index")
        if not state.current_order:
            preferences = {key: list(value) for key, value in state.preferences.items()}
            for option in options:
                if option not in preferences.setdefault("options", []):
                    preferences["options"].append(option)
            return {
                "agent": self.name,
                "handler": "update_item_option",
                "message": "好的，后面会按这个口味偏好来。",
                "patch": {"preferences": preferences},
            }
        if index is not None and 0 <= index < len(state.current_order):
            item_name = state.current_order[index].name
        item = self.menu_service.find_item_by_name(item_name)
        supported = self._supported_options(item.name if item else item_name, options)
        unsupported = self._unsupported_options(options, supported)
        updated = False
        order = state.current_order
        if supported:
            order, updated = self.order_service.update_options(state, item_name, supported, index=index)
        modifier_updated = False
        if self._has_modifier_change(modifiers):
            modifier_state = state.clone()
            modifier_state.current_order = order
            order, modifier_updated = self.order_service.update_item_modifiers(
                modifier_state,
                item_name,
                spicy_level=modifiers.get("spicy_level"),
                clear_spicy=bool(modifiers.get("clear_spicy")),
                exclusions=modifiers.get("exclusions", []),
                remove_exclusions=modifiers.get("remove_exclusions", []),
                note=modifiers.get("note"),
                replace_note=bool(modifiers.get("replace_note")),
                clear_notes=bool(modifiers.get("clear_notes")),
                index=index,
            )
        note_text = "、".join(self._unsupported_modifier_options(unsupported, modifiers))
        notes_updated = False
        if note_text:
            notes_state = state.clone()
            notes_state.current_order = order
            order, notes_updated = self.order_service.update_notes(notes_state, item_name, note_text, index=index)
        if not updated and not modifier_updated and not notes_updated:
            message = "没找到要修改的菜，我需要你再说具体一点。"
            patch = {}
        elif updated and notes_updated:
            message = f"已把{item_name}改为{self._option_text(supported).strip('（）。')}，并备注：{note_text}。"
            patch = {"current_order": order, "last_mentioned_item": item_name}
        elif notes_updated:
            message = f"好的，已备注：{note_text}。"
            patch = {"current_order": order, "last_mentioned_item": item_name}
        elif modifier_updated and not updated:
            message = f"已更新{item_name}的定制。"
            patch = {"current_order": order, "last_mentioned_item": item_name}
        else:
            message = f"已把{item_name}改为{self._option_text(supported).strip('（）。')}。"
            patch = {"current_order": order, "last_mentioned_item": item_name}
        return {
            "agent": self.name,
            "handler": "update_item_option",
            "message": message,
            "patch": patch,
        }

    def _update_item_quantity(self, interpretation: Interpretation, state: SessionState) -> dict:
        item_name = interpretation.entities.get("item_name") or (state.current_order[-1].name if state.current_order else "")
        index = interpretation.entities.get("index")
        quantity = interpretation.entities.get("quantity", 1)
        if index is not None and 0 <= index < len(state.current_order):
            item_name = state.current_order[index].name
        order, updated = self.order_service.update_quantity(state, item_name, quantity, index=index)
        patch_data = {}
        if updated:
            patch_data = {"current_order": order, "last_mentioned_item": item_name}
            self._clear_stale_pending_in_patch(state, patch_data)
        return {
            "agent": self.name,
            "handler": "update_item_quantity",
            "message": f"已把{item_name}改成 {quantity} 份。" if updated else "没找到要改数量的菜。",
            "patch": patch_data,
        }

    def _remove_item(self, interpretation: Interpretation, state: SessionState) -> dict:
        index = interpretation.entities.get("index")
        item_name = interpretation.entities.get("item_name", "")
        if index is not None:
            order, removed = self.order_service.remove_by_index(state, index)
        else:
            order, removed = self.order_service.remove_item(state, item_name)
        if removed:
            return {
                "agent": self.name,
                "handler": "remove_item",
                "message": f"已去掉{item_name or '这项'}。",
                "patch": {"current_order": order},
            }
        preferences = {key: list(value) for key, value in state.preferences.items()}
        for avoid in interpretation.preferences.get("avoid", []):
            if avoid not in preferences.setdefault("avoid", []):
                preferences["avoid"].append(avoid)
        avoid_text = "、".join(interpretation.preferences.get("avoid", [item_name]))
        return {
            "agent": self.name,
            "handler": "remove_item",
            "message": f"好的，后面推荐会避开{avoid_text}。",
            "patch": {"preferences": preferences},
        }

    def _remove_category_items(self, interpretation: Interpretation, state: SessionState) -> dict:
        category = interpretation.entities.get("category")
        order, count = self.order_service.remove_category(state, category)
        if count == 0:
            preferences = {key: list(value) for key, value in state.preferences.items()}
            if category not in preferences.setdefault("avoid", []):
                preferences["avoid"].append(category)
            return {
                "agent": self.name,
                "handler": "remove_category_items",
                "message": f"当前订单里没有{category}，后面会先避开这类。",
                "patch": {"preferences": preferences},
            }
        if count > 1:
            return {
                "agent": self.name,
                "handler": "remove_category_items",
                "message": f"订单里有 {count} 个{category}，确认都不要吗？",
                "patch": {"pending_action": {"type": "confirm_remove_category_items", "category": category, "count": count}},
            }
        return {
            "agent": self.name,
            "handler": "remove_category_items",
            "message": f"已去掉{category}里的那一项。",
            "patch": {"current_order": order},
        }

    def _replace_item(self, interpretation: Interpretation, state: SessionState) -> dict:
        old_name = interpretation.entities.get("old_item_name") or self._target_order_name(state)
        new_name = interpretation.entities.get("new_item_name")
        new_item = self.menu_service.find_item_by_name(new_name)
        if not old_name or not new_item:
            return {"agent": self.name, "handler": "replace_item", "message": "要换哪一道菜我还没确认清楚。", "patch": {}}
        options = self._supported_options(new_item.name, interpretation.preferences.get("options", []))
        order, replaced = self.order_service.replace_item(state, old_name, new_item, options=options)
        patch_data = {}
        if replaced:
            patch_data = {"current_order": order, "last_mentioned_item": new_item.name}
            self._clear_stale_pending_in_patch(state, patch_data)
        return {
            "agent": self.name,
            "handler": "replace_item",
            "message": f"已把{old_name}换成{new_item.name}。" if replaced else f"订单里没找到{old_name}。",
            "patch": patch_data,
        }

    def _clear_order(self, interpretation: Interpretation, state: SessionState) -> dict:
        return {
            "agent": self.name,
            "handler": "clear_order",
            "message": "订单已清空，你可以重新点。",
            "patch": {
                "current_order": [],
                "pending_action": None,
                "stage": "ordering",
                "last_mutation_snapshot": None,
                "last_mutation_confirmed": False,
                "last_mentioned_item": None,
                "last_mentioned_category": None,
                "viewed_category": None,
                "viewed_category_group": None,
                "preferences": {"avoid": [], "options": []},
            },
        }

    def _supported_options(self, item_name: str, options: list[str]) -> list[str]:
        supported = []
        available = self.menu_service.get_item_options(item_name)
        for option in options:
            normalized = self._normalize_option(option)
            if normalized in available or normalized in {
                "不辣",
                "微辣",
                "少辣",
                "中辣",
                "特辣",
                "清淡",
                "不要太油",
                "小份",
                "多放点汤",
                "分开放",
                "打包好一点",
            }:
                supported.append(normalized)
        return list(dict.fromkeys(supported))

    def _unsupported_options(self, options: list[str], supported: list[str]) -> list[str]:
        supported_set = set(supported)
        unsupported = []
        for option in options:
            normalized = self._normalize_option(option)
            if normalized not in supported_set:
                unsupported.append(normalized)
        return list(dict.fromkeys(unsupported))

    def _normalize_option(self, option: str) -> str:
        return "不辣" if option == "不要辣" else option

    def _option_text(self, options: list[str]) -> str:
        return f"（{','.join(options)}）" if options else ""

    def _item_detail_text(self, options: list[str], modifiers: dict) -> str:
        parts = []
        if options:
            parts.extend(options)
        if spicy_level := modifiers.get("spicy_level"):
            if spicy_level not in parts:
                parts.append(str(spicy_level))
        exclusions = modifiers.get("exclusions", [])
        parts.extend(f"不要{value}" for value in exclusions)
        if note := modifiers.get("note"):
            parts.append(f"备注：{note}")
        return f"（{'，'.join(parts)}）" if parts else ""

    def _modifiers_from_spec(self, spec: dict) -> dict:
        preferences = {
            "spicy_level": spec.get("spicy_level"),
            "exclusions": spec.get("exclusions", []),
            "note": spec.get("note"),
        }
        return self._modifiers_from_preferences(preferences)

    def _modifiers_from_preferences(self, preferences: dict) -> dict:
        return {
            "spicy_level": preferences.get("spicy_level"),
            "clear_spicy": bool(preferences.get("clear_spicy")),
            "exclusions": list(preferences.get("exclusions", [])),
            "remove_exclusions": list(preferences.get("remove_exclusions", [])),
            "note": preferences.get("note"),
            "replace_note": bool(preferences.get("replace_note")),
            "clear_notes": bool(preferences.get("clear_notes")),
        }

    def _has_modifier_change(self, modifiers: dict) -> bool:
        return any(
            [
                modifiers.get("spicy_level"),
                modifiers.get("clear_spicy"),
                modifiers.get("exclusions"),
                modifiers.get("remove_exclusions"),
                modifiers.get("note"),
                modifiers.get("replace_note"),
                modifiers.get("clear_notes"),
            ]
        )

    def _unsupported_modifier_options(self, options: list[str], modifiers: dict) -> list[str]:
        handled = set()
        if spicy_level := modifiers.get("spicy_level"):
            handled.add(spicy_level)
        return [option for option in options if option not in handled]

    def _target_order_index(self, state: SessionState) -> int:
        if state.last_mentioned_item:
            for index in range(len(state.current_order) - 1, -1, -1):
                if state.current_order[index].name == state.last_mentioned_item:
                    return index
        return len(state.current_order) - 1

    def _target_order_name(self, state: SessionState) -> str:
        if not state.current_order:
            return ""
        return state.current_order[self._target_order_index(state)].name
