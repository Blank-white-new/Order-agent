from __future__ import annotations

from app.models.schemas import Interpretation
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.state.session_state import SessionState


class MenuAgent:
    name = "MenuAgent"

    def __init__(self, menu_service: MenuService, order_service: OrderService) -> None:
        self.menu_service = menu_service
        self.order_service = order_service

    def handle(self, interpretation: Interpretation, state: SessionState) -> dict:
        handlers = {
            "ask_menu": self._ask_menu,
            "ask_category": self._ask_category,
            "ask_category_group": self._ask_category_group,
            "ask_availability": self._ask_availability,
            "ask_price": self._ask_price,
            "ask_option": self._ask_option,
            "ask_ingredient": self._ask_ingredient,
            "ask_allergen": self._ask_allergen,
            "ask_order_summary": lambda i: self._ask_order_summary(i, state),
        }
        handler = handlers.get(interpretation.intent)
        if not handler:
            return {"agent": self.name, "handler": interpretation.intent, "message": "我按菜单帮你查一下。", "patch": {}}
        return handler(interpretation)

    def _ask_menu(self, interpretation: Interpretation) -> dict:
        overview = self.menu_service.get_menu_overview(exclude_category=interpretation.entities.get("exclude_category"))
        parts = [f"{category}：{'、'.join(item.name for item in items[:4])}" for category, items in overview.items()]
        return {"agent": self.name, "handler": "ask_menu", "message": "菜单有" + "；".join(parts) + "。", "patch": {}}

    def _ask_category(self, interpretation: Interpretation) -> dict:
        exclude_category = interpretation.entities.get("exclude_category")
        if exclude_category:
            overview = self.menu_service.get_menu_overview(exclude_category=exclude_category)
            parts = [f"{category}：{'、'.join(item.name for item in items)}" for category, items in overview.items()]
            message = "除了饭，还有" + "；".join(parts) + "。"
        else:
            category = interpretation.entities.get("category") or interpretation.target
            items = self.menu_service.get_available_items_by_category(category)
            if items:
                message = f"{category}有：" + "、".join(f"{item.name}{item.price}元" for item in items) + "。"
            else:
                message = f"目前没有{category}。"
        patch = {}
        if not exclude_category and (interpretation.entities.get("category") or interpretation.target):
            patch = {
                "viewed_category": interpretation.entities.get("category") or interpretation.target,
                "last_mentioned_category": interpretation.entities.get("category") or interpretation.target,
            }
        return {"agent": self.name, "handler": "ask_category", "message": message, "patch": patch}

    def _ask_category_group(self, interpretation: Interpretation) -> dict:
        group = interpretation.entities.get("category_group") or interpretation.target
        categories = interpretation.entities.get("categories") or self.menu_service.get_categories_by_group(group)
        parts = []
        for category in categories:
            items = self.menu_service.get_available_items_by_category(category)
            if items:
                parts.append(f"{category}：{'、'.join(item.name for item in items)}")
        message = f"{group}有" + "；".join(parts) + "。" if parts else f"目前没有{group}。"
        return {
            "agent": self.name,
            "handler": "ask_category_group",
            "message": message,
            "patch": {"viewed_category_group": group, "last_mentioned_category": group},
        }

    def _ask_availability(self, interpretation: Interpretation) -> dict:
        item_name = interpretation.entities.get("item_name")
        category = interpretation.entities.get("category") or interpretation.target
        if item_name:
            item = self.menu_service.find_item_by_name(item_name)
            message = f"有{item.name}，{item.price}元。" if item and item.available else f"目前没有{item_name}。"
        elif category == "酒":
            drinks = self.menu_service.get_available_items_by_category("饮品")
            message = "目前没有酒。饮品有" + "、".join(item.name for item in drinks) + "。"
        elif category:
            items = self.menu_service.get_available_items_by_category(category)
            if items:
                message = f"有{category}，比如" + "、".join(item.name for item in items[:3]) + "。"
            else:
                message = f"目前没有{category}。"
        else:
            message = "这个我按菜单查不到，能换个菜名问我吗？"
        return {"agent": self.name, "handler": "ask_availability", "message": message, "patch": {}}

    def _ask_price(self, interpretation: Interpretation) -> dict:
        item_name = interpretation.entities.get("item_name", "")
        category = interpretation.entities.get("category")
        budget = interpretation.entities.get("budget")
        if item_name:
            item = self.menu_service.find_item_by_name(item_name)
            message = f"{item.name} {item.price} 元。" if item else "菜单里暂时没找到这个菜。"
        elif budget:
            items = self.menu_service.get_items_under_budget(int(budget))
            names = "、".join(f"{item.name}{item.price}元" for item in items)
            message = f"{budget} 元以内有：{names}。"
        elif category:
            items = self.menu_service.get_available_items_by_category(category)
            message = f"{category}价格：" + "、".join(f"{item.name}{item.price}元" for item in items) + "。"
        else:
            items = sorted(self.menu_service.all_items_as_dicts(), key=lambda item: item["price"])
            cheapest = items[0]
            message = f"最便宜的是{cheapest['name']}，{cheapest['price']}元。"
        return {"agent": self.name, "handler": "ask_price", "message": message, "patch": {}}

    def _ask_option(self, interpretation: Interpretation) -> dict:
        item_name = interpretation.entities.get("item_name", "")
        item = self.menu_service.find_item_by_name(item_name)
        if not item:
            message = "菜单里暂时没找到这个菜。"
        else:
            option = interpretation.entities.get("option")
            if option:
                normalized = "不辣" if option == "不要辣" else option
                message = f"{item.name}支持{normalized}。" if normalized in item.options else f"{item.name}暂时不支持{normalized}，可选：{'、'.join(item.options)}。"
            else:
                message = f"{item.name}可选：{'、'.join(item.options)}。"
        return {"agent": self.name, "handler": "ask_option", "message": message, "patch": {}}

    def _ask_ingredient(self, interpretation: Interpretation) -> dict:
        item_name = interpretation.entities.get("item_name")
        ingredient = interpretation.entities.get("ingredient")
        item = self.menu_service.find_item_by_name(item_name)
        if not item:
            message = "菜单里暂时没找到这个菜。"
        elif ingredient:
            message = f"{item.name}里有{ingredient}。" if ingredient in item.ingredients else f"{item.name}里没有标注{ingredient}。"
        else:
            message = f"{item.name}主要有：{'、'.join(item.ingredients)}。"
        return {"agent": self.name, "handler": "ask_ingredient", "message": message, "patch": {}}

    def _ask_allergen(self, interpretation: Interpretation) -> dict:
        allergen = interpretation.entities.get("allergen")
        blocked = []
        for item in self.menu_service.all_items_as_dicts():
            if allergen and allergen in item.get("allergens", []):
                blocked.append(item["name"])
        if blocked:
            message = f"对{allergen}过敏的话，建议避开：" + "、".join(blocked) + "。"
        else:
            message = f"菜单里暂时没有标注含{allergen}的菜。"
        return {"agent": self.name, "handler": "ask_allergen", "message": message, "patch": {}}

    def _ask_order_summary(self, interpretation: Interpretation, state: SessionState) -> dict:
        return {
            "agent": self.name,
            "handler": "ask_order_summary",
            "message": self.order_service.summarize_order(state),
            "patch": {},
        }
