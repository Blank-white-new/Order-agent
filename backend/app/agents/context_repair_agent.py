from __future__ import annotations

from app.models.schemas import Interpretation
from app.state.session_state import SessionState


class ContextRepairAgent:
    name = "ContextRepairAgent"

    def handle(self, interpretation: Interpretation, state: SessionState) -> dict:
        clarification = interpretation.entities.get("clarification", "")

        if clarification == "non_ordering_statement":
            item_name = interpretation.entities.get("item_name", "这个菜")
            return {
                "agent": self.name,
                "handler": "context_correction",
                "message": f"你是想点一份{item_name}吗？如果是，可以说“来一份{item_name}”。",
                "patch": {"pending_delivery_address_candidate": None, "stage": "ordering"},
            }

        if clarification in {
            "reference_unresolved",
            "ambiguous_reference_domain",
            "ambiguous_order_reference",
            "ambiguous_replace_reference",
            "missing_replace_target",
            "vague_order_with_question",
            "unknown_item_option",
            "multi_intent_too_many_items",
            "recommendation_index_out_of_range",
            "ambiguous_item_modifier_reference",
            "item_modifier_target_not_found",
            "missing_item_note_content",
        }:
            messages = {
                "reference_unresolved": "这个指代我没定位清楚，请说具体是哪一道菜。",
                "ambiguous_reference_domain": "这里的“第一个”可能指推荐，也可能指订单，请说具体是哪一项。",
                "ambiguous_order_reference": "订单里有多个可能对象，请说具体是哪一道菜。",
                "ambiguous_replace_reference": "要换哪一道菜我还没确认清楚，请说具体菜名。",
                "missing_replace_target": "要换哪一道菜我还没确认清楚，请说具体菜名。",
                "vague_order_with_question": "想点哪种面我还没确认清楚，请说具体菜名。",
                "unknown_item_option": "这个菜名我没识别准，请说完整菜单菜名和口味要求。",
                "multi_intent_too_many_items": "这句里有多个菜和地址电话信息，请说具体要改哪几项。",
                "recommendation_index_out_of_range": "推荐列表里没有这个序号，请说第一个、第二个或具体菜名。",
                "ambiguous_item_modifier_reference": "你想给哪一道菜设置这个定制？请说具体菜名。",
                "item_modifier_target_not_found": "订单里没找到这道菜，请说已点菜名，或直接说要加一份。",
                "missing_item_note_content": "要备注什么内容？请说具体备注，比如“汤分开放”。",
            }
            return {
                "agent": self.name,
                "handler": "context_correction",
                "message": messages[clarification],
                "patch": {"pending_delivery_address_candidate": None, "stage": "ordering"},
            }

        if clarification == "ambiguous_recommendation_reference":
            candidates = interpretation.entities.get("candidates", [])
            suffix = "当前有：" + "、".join(candidates) + "。" if candidates else ""
            return {
                "agent": self.name,
                "handler": "context_correction",
                "message": "推荐里有多个可选项，请说第几个或具体菜名。" + suffix,
                "patch": {"pending_delivery_address_candidate": None, "stage": "ordering"},
            }

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

