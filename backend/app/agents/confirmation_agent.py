from __future__ import annotations

from app.models.schemas import Interpretation
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.state.session_state import SessionState


class ConfirmationAgent:
    name = "ConfirmationAgent"

    def __init__(self, order_service: OrderService, menu_service: MenuService | None = None) -> None:
        self.order_service = order_service
        self.menu_service = menu_service or MenuService()

    def handle(self, interpretation: Interpretation, state: SessionState) -> dict:
        if state.submitted or state.submitted_order_id:
            order_id = state.submitted_order_id or "当前订单"
            return {
                "agent": self.name,
                "handler": "order_already_submitted",
                "message": (
                    f"订单已提交，订单号 {order_id}。"
                    "如需重新下单，请说“重新下单”或“再来一单”。"
                ),
                "patch": {},
            }
        if state.pending_action:
            handled = self._handle_pending_action(state)
            if handled:
                return handled
        valid, reason = self.order_service.validate_before_submit(state)
        if not valid:
            patch = {}
            if reason == "还需要配送地址。":
                patch["stage"] = "collecting_address"
            elif reason == "还需要联系电话。":
                patch["stage"] = "collecting_phone"
            return {
                "agent": self.name,
                "handler": "confirm",
                "message": reason,
                "patch": patch,
            }
        order_id = self.order_service.submit_order(state)
        summary = self.order_service.summarize_order(state)
        return {
            "agent": self.name,
            "handler": "submit_order",
            "message": f"{summary} 订单已确认并保存到模拟系统，尚未发送给真实餐厅。模拟订单号 {order_id}。",
            "patch": {
                "submitted": True,
                "submitted_order_id": order_id,
                "stage": "submitted",
                "lifecycle_status": "CUSTOMER_CONFIRMED",
                "merchant_status": "NOT_INTEGRATED",
                "confirmation_valid": True,
            },
        }

    def _handle_pending_action(self, state: SessionState) -> dict | None:
        action = state.pending_action or {}
        action_type = action.get("type")
        if action_type == "confirm_order_category_items":
            quantity_each = action.get("quantity_each", 1)
            specs = []
            for name in action.get("item_names", []):
                item = self.menu_service.find_item_by_name(name)
                if item:
                    specs.append({"item": item, "quantity": quantity_each, "source": "confirm_order_category_items"})
            order = self.order_service.add_items(state, specs) if specs else list(state.current_order)
            return {
                "agent": self.name,
                "handler": "confirm_pending_action",
                "message": "已按确认加入：" + "、".join(action.get("item_names", [])) + "。",
                "patch": {"current_order": order, "pending_action": None, "stage": "ordering"},
            }
        if action_type == "confirm_remove_category_items":
            category = action.get("category")
            order, count = self.order_service.remove_category(state, category)
            return {
                "agent": self.name,
                "handler": "confirm_pending_action",
                "message": f"已去掉{count}个{category}。",
                "patch": {"current_order": order, "pending_action": None},
            }
        if action_type == "confirm_clear_order":
            return {
                "agent": self.name,
                "handler": "confirm_pending_action",
                "message": "已清空订单，可以重新点餐。",
                "patch": {
                    "current_order": [],
                    "pending_action": None,
                    "stage": "ordering",
                    "last_mutation_snapshot": None,
                    "last_mutation_confirmed": False,
                },
            }
        if action_type == "conditional_order":
            proposed = action.get("proposed_action", {})
            entities = proposed.get("entities", {})
            item = self.menu_service.find_item_by_name(entities.get("item_name"))
            if not item:
                return {
                    "agent": self.name,
                    "handler": "confirm_pending_action",
                    "message": "这个待确认菜品菜单里没找到。",
                    "patch": {"pending_action": None},
                }
            preferences = proposed.get("preferences", {})
            options = [option for option in preferences.get("options", []) if option in item.options or option in {"清淡", "不要太油"}]
            order = self.order_service.add_item(
                state,
                item,
                quantity=entities.get("quantity", 1),
                options=options,
                unit=entities.get("unit"),
                source="conditional_order",
            )
            return {
                "agent": self.name,
                "handler": "confirm_pending_action",
                "message": f"已加入{item.name}。",
                "patch": {"current_order": order, "pending_action": None, "stage": "ordering", "last_mentioned_item": item.name},
            }
        return None
