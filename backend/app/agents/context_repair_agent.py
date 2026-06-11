from __future__ import annotations

from app.models.schemas import Interpretation
from app.state.session_state import SessionState


class ContextRepairAgent:
    name = "ContextRepairAgent"

    def handle(self, interpretation: Interpretation, state: SessionState) -> dict:
        clarification = interpretation.entities.get("clarification", "")

        if clarification == "ambiguous_dish_fragment":
            candidates = interpretation.entities.get("candidates", [])
            if len(candidates) >= 2:
                message = "你是说" + "、".join(candidates[:-1]) + "，还是" + candidates[-1] + "？可以说菜名或第几个。"
                pending = {
                    "type": "select_ambiguous_dish_candidate",
                    "candidates": [{"name": name} for name in candidates],
                    "source_text": interpretation.entities.get("raw", ""),
                }
                return {
                    "agent": self.name,
                    "handler": "context_correction",
                    "message": message,
                    "patch": {
                        "pending_action": pending,
                        "pending_delivery_address_candidate": None,
                        "stage": "ordering",
                    },
                }
            if len(candidates) == 1:
                message = "你是说" + candidates[0] + "吗？"
                pending = {
                    "type": "select_ambiguous_dish_candidate",
                    "candidates": [{"name": candidates[0]}],
                    "source_text": interpretation.entities.get("raw", ""),
                }
                return {
                    "agent": self.name,
                    "handler": "context_correction",
                    "message": message,
                    "patch": {
                        "pending_action": pending,
                        "pending_delivery_address_candidate": None,
                        "stage": "ordering",
                    },
                }
            message = "菜单里没找到这个菜，能换个菜名吗？"
            return {
                "agent": self.name,
                "handler": "context_correction",
                "message": message,
                "patch": {
                    "pending_delivery_address_candidate": None,
                    "stage": "ordering",
                },
            }

        if clarification == "ambiguous_no_dish_fragment":
            candidates = interpretation.entities.get("candidates", [])
            if candidates:
                message = "你想要第几个？可以说第一个、第二个，或者直接说菜名。当前有：" + "、".join(candidates[:3]) + "。"
            else:
                message = "请说清楚菜名或第几个，比如「第一个」或「鸡腿饭」。"
            return {
                "agent": self.name,
                "handler": "context_correction",
                "message": message,
                "patch": {
                    "pending_delivery_address_candidate": None,
                    "stage": "ordering",
                },
            }

        if not state.current_order:
            message = "确实还没点菜，我先把刚才的待确认内容清掉。"
        else:
            message = "明白，我先清掉刚才的待确认内容，订单本身先不动。"
        return {
            "agent": self.name,
            "handler": "context_correction",
            "message": message,
            "patch": {
                "pending_delivery_address_candidate": None,
                "stage": "ordering",
            },
        }

