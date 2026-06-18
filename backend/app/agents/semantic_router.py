from __future__ import annotations

import re

from app.agents.semantic_rules import (
    detect_category_group_query,
    detect_composite_intent,
    detect_conditional_order,
    detect_subjective_ranking_query,
)
from app.models.schemas import Interpretation
from app.services.menu_service import MenuService


QUESTION_MARKERS = (
    "?", "？", "吗", "啥", "什么", "怎么", "怎样", "如何", "为什么", "为啥",
    "哪里", "哪儿", "哪边", "哪个", "哪些", "多少", "多久", "几",
    "有没有", "能不能", "能送", "呢",
)
CONFIRM_WORDS = {"确认", "可以", "好的", "好", "对", "是的", "没错", "没问题", "就这样", "就这些", "先这样", "下单", "提交订单", "用这个地址", "就这个地址"}
CANCEL_WORDS = {"不用", "不要了", "算了", "取消", "先不点了", "不点了", "先不买了"}
ORDER_ACTION_TOKENS = (
    "来一份",
    "来一个",
    "来个",
    "来一",
    "再来",
    "再加",
    "点",
    "加",
    "要",
    "想要",
    "我要",
)
ADDRESS_TOKENS = (
    "大学",
    "校区",
    "校园",
    "小区",
    "宿舍",
    "楼",
    "楼上",
    "楼下",
    "栋",
    "单元",
    "室",
    "号",
    "路",
    "街",
    "巷",
    "学院",
    "公司",
    "园区",
    "地铁站",
    "饭店",
    "餐厅",
    "饭堂",
    "旁边",
    "附近",
    "门口",
    "对面",
)
ADDRESS_PLACE_SUFFIXES = ("店", "饭店", "餐厅", "饭堂", "楼", "楼上", "楼下", "旁边", "附近", "门口", "对面")

OPTION_TOKENS = [
    "不辣",
    "不要辣",
    "少辣",
    "微辣",
    "中辣",
    "加辣",
    "不要香菜",
    "不香菜",
    "不要葱",
    "不葱",
    "不要太油",
    "清淡点",
    "大份",
    "小份",
    "标准",
    "加蛋",
    "加青菜",
    "去冰",
    "少冰",
    "热的",
    "多放点汤",
    "分开放",
    "打包好一点",
    "冰",
]

CHINESE_NUMBERS = {
    "零": 0,
    "一": 1,
    "一个": 1,
    "一份": 1,
    "一瓶": 1,
    "一杯": 1,
    "两": 2,
    "二": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "六个": 6,
    "六份": 6,
    "六瓶": 6,
    "七": 7,
    "七个": 7,
    "七份": 7,
    "七瓶": 7,
    "八": 8,
    "八个": 8,
    "八份": 8,
    "八瓶": 8,
    "九": 9,
    "九个": 9,
    "九份": 9,
    "九瓶": 9,
    "十": 10,
    "十个": 10,
    "十份": 10,
    "十瓶": 10,
}


class SemanticRouterAgent:
    def __init__(self, menu_service: MenuService | None = None) -> None:
        self.menu_service = menu_service or MenuService()

    def normalize(self, message: str) -> str:
        return re.sub(r"\s+", "", message.strip())

    def interpret(self, message: str) -> Interpretation:
        text = self.normalize(message)
        compact = self._compact(text)

        if self._is_context_correction(compact):
            return Interpretation(intent="context_correction", confidence=0.98, source="rule", should_mutate_order=False)

        conditional = detect_conditional_order(compact, self.menu_service)
        if conditional:
            return Interpretation(
                intent="conditional_order",
                confidence=0.94,
                source="rule",
                is_question=True,
                should_mutate_order=False,
                entities={"conditionalDecision": conditional},
            )

        composite = detect_composite_intent(compact, self.menu_service)
        if composite and self._should_use_composite(composite):
            return Interpretation(
                intent="composite_intent",
                confidence=0.94,
                source="rule",
                is_question=any(child.get("is_question") for child in composite["children"]),
                should_mutate_order=any(child.get("should_mutate_order") for child in composite["children"]),
                entities={"children": composite["children"]},
            )

        if self._is_context_reference(compact):
            return Interpretation(
                intent="context_reference_resolution",
                confidence=0.9,
                source="rule",
                should_mutate_order=self._reference_should_mutate(compact),
                entities={"reference": self._extract_reference(compact), "raw": compact},
                preferences=self._extract_preferences(compact),
            )

        if self._is_clear_order(compact):
            return Interpretation(intent="clear_order", confidence=0.96, source="rule", should_mutate_order=True)

        if compact in CONFIRM_WORDS:
            return Interpretation(intent="confirm", confidence=0.95, source="rule", should_mutate_order=False)

        if compact in CANCEL_WORDS:
            return Interpretation(intent="cancel", confidence=0.9, source="rule", should_mutate_order=False)

        if phone := self._extract_phone(compact):
            return Interpretation(
                intent="provide_phone",
                confidence=0.95,
                source="deterministic",
                should_mutate_order=True,
                entities={"phone": phone},
            )

        delivery = self._interpret_delivery(compact)
        if delivery:
            return delivery

        menu_info = self._interpret_menu_information(compact)
        if menu_info:
            return menu_info

        recommendation = self._interpret_recommendation(compact)
        if recommendation:
            return recommendation

        address_order = self._interpret_address_order_mix(compact)
        if address_order:
            return address_order

        if self._looks_like_address_text(compact) and not self._has_explicit_order_action(compact):
            return Interpretation(intent="fallback", confidence=0.2, source="deterministic", is_question=False)

        repeat = self._interpret_repeat_last_item(compact)
        if repeat:
            return repeat

        category_order = self._interpret_category_order(compact)
        if category_order:
            return category_order

        replacement = self._interpret_replacement(compact)
        if replacement:
            return replacement

        multiple_order = self._interpret_multiple_order(compact)
        if multiple_order:
            return multiple_order

        single_order = self._interpret_single_order(compact)
        if single_order:
            return single_order

        modification = self._interpret_modification(compact)
        if modification:
            return modification

        fulfillment = self._interpret_fulfillment(compact)
        if fulfillment:
            return fulfillment

        if self._is_smalltalk(compact):
            return Interpretation(intent="smalltalk", confidence=0.75, source="deterministic", is_question=self._looks_like_question(compact))

        return Interpretation(intent="fallback", confidence=0.2, source="deterministic", is_question=self._looks_like_question(compact))

    def _compact(self, text: str) -> str:
        return re.sub(r"[，,。！？!?；;、\s]", "", text)

    def _interpret_delivery(self, text: str) -> Interpretation | None:
        if "配送费" in text or "外卖费" in text or self._looks_like_delivery_fee_question(text):
            address = self._extract_address(text, ["送到", "外卖到", "到", "配送费", "外卖费", "多少钱", "多少"])
            return Interpretation(
                intent="ask_delivery_fee",
                confidence=0.96,
                source="rule",
                is_question=True,
                should_mutate_order=False,
                entities={"address": address} if address else {},
            )
        if any(token in text for token in ["送多久", "要多久", "配送要多久", "外卖多久", "多久能送到", "多久到"]):
            address = self._extract_address(text, ["送到", "外卖到", "到", "要送多久", "送多久", "配送要多久", "外卖多久", "多久能送到", "多久到", "要多久"])
            return Interpretation(
                intent="ask_delivery_eta",
                confidence=0.96,
                source="rule",
                is_question=True,
                should_mutate_order=False,
                entities={"address": address} if address else {},
            )
        if any(token in text for token in ["能送到", "能送", "能配送"]):
            address = self._extract_address(text, ["送到", "到", "能送到吗", "能送吗", "能配送吗", "能送到", "能送", "能配送"])
            return Interpretation(
                intent="ask_deliverability",
                confidence=0.96,
                source="rule",
                is_question=True,
                should_mutate_order=False,
                entities={"address": address} if address else {},
            )
        return None

    def _interpret_menu_information(self, text: str) -> Interpretation | None:
        item = self.menu_service.find_item_by_name(text)
        category = self.menu_service.find_category_by_alias(text)
        group = detect_category_group_query(text)
        if "推荐" in text:
            return None

        if self._is_order_summary_question(text):
            return Interpretation(intent="ask_order_summary", confidence=0.94, source="rule", is_question=True)

        if self._is_allergen_question(text):
            return Interpretation(
                intent="ask_allergen",
                confidence=0.9,
                source="rule",
                is_question=True,
                entities={"item_name": item.name if item else None, "allergen": self._extract_allergen(text)},
            )

        if item and self._is_ingredient_question(text):
            return Interpretation(
                intent="ask_ingredient",
                confidence=0.92,
                source="rule",
                is_question=True,
                entities={"item_name": item.name, "ingredient": self._extract_ingredient(text)},
            )

        if self._is_preference_query(text):
            return Interpretation(
                intent="ask_recommendation_by_preference",
                confidence=0.9,
                source="rule",
                is_question=True,
                preferences=self._extract_preferences(text),
            )

        if item and self._is_price_question(text):
            return Interpretation(intent="ask_price", confidence=0.96, source="rule", is_question=True, entities={"item_name": item.name})

        if (category or any(token in text for token in ["最便宜", "价格", "元以内"])) and self._is_price_question(text):
            entities = {"category": category} if category else {}
            if budget := self._extract_budget(text):
                entities["budget"] = budget
            return Interpretation(intent="ask_price", confidence=0.9, source="rule", is_question=True, entities=entities)

        if item and self._is_option_question(text):
            return Interpretation(
                intent="ask_option",
                confidence=0.94,
                source="rule",
                is_question=True,
                entities={"item_name": item.name, "option": self._extract_option_name(text)},
            )

        if self._is_availability_question(text):
            entities = {}
            if item:
                entities["item_name"] = item.name
            if category:
                entities["category"] = category
            if "酒" in text:
                entities["category"] = "酒"
            return Interpretation(
                intent="ask_availability",
                confidence=0.95,
                source="rule",
                is_question=True,
                entities=entities,
                target=entities.get("category") or entities.get("item_name"),
            )

        if group and group["group"] in {"主食", "正餐"} and self._is_category_group_question(text):
            return Interpretation(
                intent="ask_category_group",
                confidence=0.93,
                source="rule",
                is_question=True,
                entities={"category_group": group["group"], "categories": group["categories"]},
                target=group["group"],
            )

        if self._is_category_question(text, category):
            entities = {"category": category}
            if "除了饭" in text or "饭以外" in text or "不想吃饭" in text:
                entities = {"exclude_category": "饭类"}
            return Interpretation(intent="ask_category", confidence=0.93, source="rule", is_question=True, entities=entities, target=category)

        if self._is_menu_question(text):
            return Interpretation(intent="ask_menu", confidence=0.95, source="rule", is_question=True)

        if category and text in {"饭", "米饭", "盖饭", "小吃", "饮品", "饮料", "喝的", "面", "面类"}:
            return Interpretation(intent="ask_category", confidence=0.9, source="deterministic", is_question=True, entities={"category": category}, target=category)

        if item and self._looks_like_question(text):
            entities = {"item_name": item.name}
            if self._is_ingredient_question(text):
                entities["ingredient"] = self._extract_ingredient(text)
                return Interpretation(intent="ask_ingredient", confidence=0.88, source="rule", is_question=True, entities=entities)
            if self._is_price_question(text):
                return Interpretation(intent="ask_price", confidence=0.88, source="rule", is_question=True, entities=entities)
            if self._is_option_question(text):
                return Interpretation(intent="ask_option", confidence=0.88, source="rule", is_question=True, entities=entities)
            return Interpretation(intent="ask_ingredient", confidence=0.85, source="rule", is_question=True, entities=entities)

        return None

    def _interpret_recommendation(self, text: str) -> Interpretation | None:
        if self.menu_service.find_item_by_name(text) and "推荐" not in text:
            return None
        category = self.menu_service.find_category_by_alias(text)
        ranking = detect_subjective_ranking_query(text, self.menu_service)
        if ranking["is_ranking"]:
            entities = {
                "category": ranking["category"],
                "category_group": ranking["category_group"],
                "categories": ranking["categories"],
                "sales_claim_requested": ranking["sales_claim_requested"],
            }
            return Interpretation(
                intent="ask_recommendation_by_category_ranked",
                confidence=0.9,
                source="rule",
                is_question=True,
                entities=entities,
                preferences={"category": ranking["category"]} if ranking["category"] else {},
            )
        if self._is_recommendation_refresh(text):
            return Interpretation(intent="ask_recommendation", confidence=0.9, source="rule", is_question=True)
        if "推荐" in text and category:
            return Interpretation(
                intent="ask_recommendation_by_category",
                confidence=0.94,
                source="rule",
                is_question=True,
                entities={"category": category},
                preferences={"category": category},
            )
        if self._is_budget_recommendation(text):
            return Interpretation(
                intent="ask_recommendation_by_budget",
                confidence=0.92,
                source="rule",
                is_question=True,
                entities={"budget": self._extract_budget(text)},
                preferences={"budget": self._extract_budget(text)},
            )
        if self._is_speed_recommendation(text):
            return Interpretation(intent="ask_recommendation_by_speed", confidence=0.88, source="rule", is_question=True, preferences={"options": ["快"]})
        if self._is_preference_recommendation(text):
            return Interpretation(
                intent="ask_recommendation_by_preference",
                confidence=0.88,
                source="rule",
                is_question=True,
                preferences=self._extract_preferences(text),
            )
        if text in {
            "推荐",
            "推荐一下",
            "推荐点",
            "推荐点好吃的",
            "推荐个菜",
            "推荐几个菜",
            "你推荐",
            "你推荐什么",
            "你有什么推荐",
            "有什么推荐",
            "有啥推荐的",
            "有啥好推荐的",
            "有啥好吃的",
            "不知道吃啥",
            "随便推荐一个",
            "随便来一个",
            "随便来个好吃的",
            "随便",
            "你看着办",
            "来个好吃的",
        }:
            return Interpretation(intent="ask_recommendation", confidence=0.95, source="rule", is_question=True)
        return None

    def _interpret_category_order(self, text: str) -> Interpretation | None:
        category = self.menu_service.find_category_by_alias(text)
        if not category:
            return None
        if any(token in text for token in ["各来", "都来", "每样", "每种", "都要"]) and not self._looks_like_question(text) and "推荐" not in text:
            return Interpretation(
                intent="order_category_items",
                confidence=0.94,
                source="rule",
                should_mutate_order=True,
                entities={"category": category, "quantity_each": self._extract_quantity(text), "unit": self._extract_unit(text)},
            )
        return None

    def _interpret_repeat_last_item(self, text: str) -> Interpretation | None:
        if self.menu_service.find_item_by_name(text) or self._looks_like_question(text):
            return None
        repeat_patterns = [
            "再来一份",
            "再来一个",
            "再加一份",
            "再加一个",
            "加一份",
            "加一个",
            "同样的再来一份",
            "同样再来一份",
        ]
        if text in repeat_patterns or (
            ("再来" in text or "再加" in text or text.startswith("加"))
            and any(unit in text for unit in ["份", "个", "瓶", "杯"])
        ):
            return Interpretation(
                intent="repeat_last_item",
                confidence=0.9,
                source="rule",
                should_mutate_order=True,
                entities={"quantity": self._extract_quantity(text), "unit": self._extract_unit(text)},
            )
        return None

    def _interpret_multiple_order(self, text: str) -> Interpretation | None:
        if "换成" in text or "换" in text:
            return None
        items = self.menu_service.find_items_in_text(text)
        if len(items) < 2:
            return None
        if self._looks_like_question(text):
            return None
        return Interpretation(
            intent="order_multiple_items",
            confidence=0.92,
            source="rule",
            should_mutate_order=True,
            entities={"items": self._extract_item_specs(text, items)},
            preferences=self._extract_preferences(text),
        )

    def _interpret_single_order(self, text: str) -> Interpretation | None:
        item = self.menu_service.find_item_by_name(text)
        if not item or self._looks_like_question(text) or text.startswith("不要"):
            return None
        if any(token in text for token in ["改成", "换成", "不要了", "多少钱", "价格"]):
            return None
        return Interpretation(
            intent="order_food",
            confidence=0.93,
            source="rule",
            should_mutate_order=True,
            entities={"item_name": item.name, "quantity": self._extract_quantity(text), "unit": self._extract_unit(text)},
            preferences=self._extract_preferences(text),
        )

    def _interpret_address_order_mix(self, text: str) -> Interpretation | None:
        if not self._looks_like_address_text(text) or not self._has_explicit_order_action(text):
            return None
        items = self._items_with_order_evidence(text)
        if not items:
            return Interpretation(
                intent="fallback",
                confidence=0.86,
                source="deterministic",
                is_question=False,
                should_mutate_order=False,
                entities={"directed_message": "这句里有地址和点菜信息，我没确认具体要加哪个菜。请把菜名和地址分开发我。"},
            )
        if len(items) > 1:
            return Interpretation(
                intent="fallback",
                confidence=0.86,
                source="deterministic",
                is_question=False,
                should_mutate_order=False,
                entities={"directed_message": "这句里有多个菜和地址，我先不改订单。请把要点的菜和配送地址分开发我。"},
            )

        item, position = items[0]
        children = [
            {
                "intent": "order_food",
                "confidence": 0.93,
                "source": "rule",
                "is_question": False,
                "should_mutate_order": True,
                "entities": {"item_name": item.name, "quantity": self._extract_quantity(text), "unit": self._extract_unit(text)},
                "preferences": self._extract_preferences(text),
                "target": item.name,
                "raw": item.name,
            }
        ]
        address = self._extract_mixed_address(text, position)
        if address:
            children.append(
                {
                    "intent": "replace_delivery_candidate",
                    "confidence": 0.88,
                    "source": "rule",
                    "is_question": False,
                    "should_mutate_order": True,
                    "entities": {"address": address},
                    "preferences": {},
                    "target": address,
                    "raw": address,
                }
            )
        if len(children) == 1:
            child = children[0]
            return Interpretation(
                intent="order_food",
                confidence=child["confidence"],
                source="rule",
                should_mutate_order=True,
                entities=child["entities"],
                preferences=child["preferences"],
                target=child["target"],
            )
        return Interpretation(
            intent="composite_intent",
            confidence=0.92,
            source="rule",
            should_mutate_order=True,
            entities={"children": children},
        )

    def _items_with_order_evidence(self, text: str) -> list[tuple[object, int]]:
        matches: list[tuple[int, int, object]] = []
        for item in self.menu_service.find_items_in_text(text):
            evidence = self._best_item_evidence_span(text, item)
            if evidence is None:
                continue
            position, length = evidence
            matches.append((position, length, item))
        matches.sort(key=lambda match: (match[0], -match[1]))
        return [(item, position) for position, _length, item in matches]

    def _best_item_evidence_span(self, text: str, item: object) -> tuple[int, int] | None:
        names = self.menu_service.matching_names_for_item(getattr(item, "name", ""))
        spans: list[tuple[int, int]] = []
        for name in names:
            if not name:
                continue
            start = text.find(name)
            while start >= 0:
                end = start + len(name)
                if not self._is_embedded_in_address_place(text, end) and self._has_order_action_near_span(text, start, end):
                    spans.append((start, len(name)))
                start = text.find(name, start + 1)
        if not spans:
            return None
        return sorted(spans, key=lambda span: (span[0], -span[1]))[0]

    def _is_embedded_in_address_place(self, text: str, end: int) -> bool:
        tail = text[end : end + 4]
        return any(tail.startswith(suffix) for suffix in ADDRESS_PLACE_SUFFIXES)

    def _has_order_action_near_span(self, text: str, start: int, end: int) -> bool:
        window = text[max(0, start - 8) : min(len(text), end + 8)]
        if any(token in window for token in ORDER_ACTION_TOKENS):
            return True
        return bool(re.search(r"(?:\d+|[一二两俩三四五六七八九十]+)(?:份|个|瓶|杯|碗)", window))

    def _extract_mixed_address(self, text: str, item_position: int) -> str | None:
        order_positions = [text.find(token) for token in ORDER_ACTION_TOKENS if token in text]
        before_item_order_positions = [position for position in order_positions if 0 <= position < item_position]
        boundary = min(before_item_order_positions, default=item_position)
        address = text[:boundary]
        if not address and "送到" in text:
            address = text[text.find("送到") : item_position]
        for token in ["配送到", "外卖到", "送到", "配送", "外卖", "到"]:
            address = address.replace(token, "")
        address = address.strip()
        return address if self._looks_like_address_text(address) else None

    def _looks_like_address_text(self, text: str) -> bool:
        if not text:
            return False
        if any(token in text for token in ["有啥", "喝的", "菜单", "配送费", "多久", "确认", "不用"]):
            return False
        return any(token in text for token in ADDRESS_TOKENS)

    def _has_explicit_order_action(self, text: str) -> bool:
        if not text or text.startswith("不要"):
            return False
        if any(token in text for token in ORDER_ACTION_TOKENS):
            return True
        return bool(re.search(r"(?:\d+|[一二两俩三四五六七八九十]+)(?:份|个|瓶|杯|碗)", text))

    def _interpret_replacement(self, text: str) -> Interpretation | None:
        if "换成" not in text and "换" not in text:
            return None
        items = self.menu_service.find_items_in_text(text)
        if len(items) >= 2:
            return Interpretation(
                intent="replace_item",
                confidence=0.92,
                source="rule",
                should_mutate_order=True,
                entities={"old_item_name": items[0].name, "new_item_name": items[1].name},
                preferences=self._extract_preferences(text),
            )
        if len(items) == 1:
            return Interpretation(
                intent="replace_item",
                confidence=0.9,
                source="rule",
                should_mutate_order=True,
                entities={"new_item_name": items[0].name},
                preferences=self._extract_preferences(text),
            )
        if any(token in text for token in ["不辣", "清淡", "便宜"]):
            return Interpretation(
                intent="replace_item",
                confidence=0.8,
                source="rule",
                should_mutate_order=True,
                preferences=self._extract_preferences(text),
            )
        return None

    def _interpret_modification(self, text: str) -> Interpretation | None:
        item = self.menu_service.find_item_by_name(text)
        category = self.menu_service.find_category_by_alias(text)
        if self._is_clear_order(text):
            return Interpretation(intent="clear_order", confidence=0.96, source="rule", should_mutate_order=True)
        if item and (text.startswith("不要") or "不要了" in text):
            avoid = "牛肉" if "牛肉" in item.name else item.name
            return Interpretation(
                intent="remove_item",
                confidence=0.94,
                source="rule",
                should_mutate_order=True,
                entities={"item_name": item.name},
                preferences={"avoid": [avoid]},
            )
        if category and not item and any(token in text for token in ["不要了", "都不要", "不要"]):
            return Interpretation(
                intent="remove_category_items",
                confidence=0.9,
                source="rule",
                should_mutate_order=True,
                entities={"category": category},
            )
        if item and any(
            token in text
            for token in [
                "改成",
                "不要辣",
                "不辣",
                "少辣",
                "微辣",
                "大份",
                "小份",
                "加蛋",
                "加青菜",
                "不要香菜",
                "不香菜",
                "不要葱",
                "不葱",
                "去冰",
                "少冰",
            ]
        ):
            quantity = self._extract_quantity(text)
            if any(unit in text for unit in ["两份", "2份", "两瓶", "2瓶", "三份", "3份", "改成两", "改成2", "改成三"]):
                return Interpretation(
                    intent="update_item_quantity",
                    confidence=0.9,
                    source="rule",
                    should_mutate_order=True,
                    entities={"item_name": item.name, "quantity": quantity, "unit": self._extract_unit(text)},
                )
            return Interpretation(
                intent="update_item_option",
                confidence=0.9,
                source="rule",
                should_mutate_order=True,
                entities={"item_name": item.name},
                preferences=self._extract_preferences(text),
            )
        if text.startswith("不要") and any(token in text for token in ["辣", "香菜", "葱", "太油"]):
            return Interpretation(
                intent="ask_recommendation_by_preference",
                confidence=0.86,
                source="deterministic",
                should_mutate_order=False,
                preferences=self._extract_preferences(text),
            )
        return None

    def _interpret_fulfillment(self, text: str) -> Interpretation | None:
        if text in {"配送", "外卖", "送过来", "改成配送"}:
            return Interpretation(
                intent="provide_fulfillment_slot",
                confidence=0.92,
                source="rule",
                should_mutate_order=True,
                entities={"fulfillment_type": "delivery"},
            )
        if text in {"自取", "到店取", "我自己拿", "还是自取吧"}:
            return Interpretation(
                intent="provide_fulfillment_slot",
                confidence=0.92,
                source="rule",
                should_mutate_order=True,
                entities={"fulfillment_type": "pickup"},
            )
        return None

    def _is_context_correction(self, text: str) -> bool:
        patterns = [
            "刚才啥也没点",
            "我还没点",
            "我没点东西",
            "哪来的订单",
            "你理解错了",
            "不是这个",
            "我不是这个意思",
            "你说错了",
            "我不是要这个",
            "我不是问这个",
            "我只是问一下",
            "你别乱加",
            "我没说要点",
            "我没点",
            "没让你加",
            "加错了",
            "不对",
            "不是我要的",
            "弄错了",
            "搞错了",
            "误会了",
            "我只是问问",
            "我不是要点",
            "我只是想问",
            "我没说要",
            "我没想点",
            "我不是要这个",
        ]
        return any(pattern in text for pattern in patterns)

    def _is_context_reference(self, text: str) -> bool:
        if "能送" in text or "能配送" in text:
            return False
        if text in {"第一个", "第二个", "第三个", "就这个", "要这个", "就那个", "要那个", "来那个"}:
            return True
        reference_tokens = ["这个", "那个", "第一个", "第二个", "第三个", "刚才那个", "这些", "那些"]
        if text in {"就这个", "要这个"}:
            return False
        has_reference = any(token in text for token in reference_tokens)
        if not has_reference:
            return False
        has_action = any(
            action in text
            for action in [
                "不要辣",
                "不辣",
                "少辣",
                "微辣",
                "不要香菜",
                "不香菜",
                "不要葱",
                "不葱",
                "去冰",
                "少冰",
                "加蛋",
                "加青菜",
                "改成",
                "不要了",
                "都要",
                "能送到",
                "能送",
                "大份",
                "小份",
            ]
        )
        if has_action:
            return True
        items = self.menu_service.find_items_in_text(text)
        if items:
            return True
        return self._has_dish_name_fragment(text)

    def _has_dish_name_fragment(self, text: str) -> bool:
        """Check if removing reference tokens leaves a fragment matching a menu item."""
        import re
        fragment = re.sub(r"(这个|那个|这些|那些|第一个|第二个|第三个|刚才那个)", "", text).strip()
        if len(fragment) < 2:
            return False
        for item_dict in self.menu_service.all_items_as_dicts():
            name = item_dict.get("name", "")
            aliases = item_dict.get("aliases", [])
            for n in [name, *aliases]:
                if n and len(n) >= 2:
                    if fragment in n:
                        return True
        return False

    def _reference_should_mutate(self, text: str) -> bool:
        return any(
            token in text
            for token in [
                "不要辣",
                "不辣",
                "少辣",
                "微辣",
                "不要香菜",
                "不香菜",
                "不要葱",
                "不葱",
                "去冰",
                "少冰",
                "加蛋",
                "加青菜",
                "改成",
                "不要了",
                "都要",
                "大份",
                "小份",
            ]
        )

    def _extract_reference(self, text: str) -> str:
        for token in ["第一个", "第二个", "第三个", "刚才那个", "这些", "那些", "这个", "那个"]:
            if token in text:
                return token
        return text

    def _is_order_summary_question(self, text: str) -> bool:
        return any(pattern in text for pattern in ["我点了什么", "点了什么", "订单", "我点啥", "现在多少钱", "总共多少钱", "帮我看下订单", "订单看一下"])

    def _is_allergen_question(self, text: str) -> bool:
        return "过敏" in text or "不能点" in text

    def _is_ingredient_question(self, text: str) -> bool:
        return any(token in text for token in ["里面有什么", "有什么配料", "有香菜吗", "有鸡蛋吗", "含", "不含"])

    def _is_preference_query(self, text: str) -> bool:
        return any(token in text for token in ["我不吃", "有没有不辣", "有没有素", "有没有清淡", "哪些不含"])

    def _is_price_question(self, text: str) -> bool:
        return any(token in text for token in ["多少钱", "多少", "价格", "最便宜", "元以内"])

    def _is_option_question(self, text: str) -> bool:
        return self._looks_like_question(text) and any(token in text for token in OPTION_TOKENS + ["口味", "可以", "能"])

    def _is_availability_question(self, text: str) -> bool:
        return (
            "有没有" in text
            or text.endswith("有吗")
            or text.endswith("还有吗")
            or "卖完了吗" in text
            or "今天有" in text
            or (text.startswith("有") and text.endswith("吗"))
        )

    def _is_category_question(self, text: str, category: str | None) -> bool:
        if "推荐" in text:
            return False
        if "各来" in text or "都来" in text or "每样" in text:
            return False
        return bool(category and (any(token in text for token in ["有什么", "有啥", "看看", "只看", "以外", "除了", "不想吃"]) or text in {category}))

    def _is_category_group_question(self, text: str) -> bool:
        return text in {"主食", "正餐"} or any(token in text for token in ["有什么", "有啥", "有哪些", "看"])

    def _is_menu_question(self, text: str) -> bool:
        exact = {"有啥", "都有啥呀", "都有啥", "菜单有啥", "菜单有什么", "有什么吃的", "你们这有什么吃的", "卖什么", "点什么", "可以吃什么", "看菜单"}
        if text in exact:
            return True
        return ("菜单" in text or "有什么吃" in text or "卖什么" in text) and "推荐" not in text

    def _is_recommendation_refresh(self, text: str) -> bool:
        return text in {"换一个", "还有别的吗", "还有别的么", "再推荐一个"}

    def _is_budget_recommendation(self, text: str) -> bool:
        return "推荐" in text and self._extract_budget(text) is not None

    def _is_preference_recommendation(self, text: str) -> bool:
        return any(token in text for token in ["清淡", "不辣", "便宜", "舒服", "有汤", "热乎", "不要太油", "不吃牛肉", "不要香菜", "主食", "小份", "一个人吃"])

    def _is_speed_recommendation(self, text: str) -> bool:
        if not any(token in text for token in ["快一点", "快点", "快的", "出餐快", "赶时间", "马上"]):
            return False
        if any(token in text for token in ["推荐", "出餐", "赶时间", "马上", "来个快", "来点快", "要个快"]):
            return True
        return text in {"快点", "快一点的", "快点的", "快的"}

    def _should_use_composite(self, composite: dict) -> bool:
        intents = {child.get("intent") for child in composite.get("children", [])}
        has_order = bool(intents & {"order_food", "order_multiple_items", "order_category_items", "order_category_group_items"})
        has_delivery = bool(intents & {"ask_delivery_eta", "ask_delivery_fee", "ask_deliverability"})
        has_info = bool(intents & {"ask_price", "ask_option", "ask_category", "ask_menu"})
        return has_order and (has_delivery or has_info)

    def _is_clear_order(self, text: str) -> bool:
        return text in {"清空订单", "全部不要了", "都不要了", "全都不要了"}

    def _is_smalltalk(self, text: str) -> bool:
        return any(token in text for token in ["月亮", "天气", "你好", "谢谢", "笑话", "你是谁", "哈哈"])

    def _looks_like_question(self, text: str) -> bool:
        return any(marker in text for marker in QUESTION_MARKERS)

    def _looks_like_delivery_fee_question(self, text: str) -> bool:
        address_tokens = ["到", "送到", "学校", "大学", "校区", "校园", "东门", "北门", "宿舍", "楼下"]
        return "多少钱" in text and any(token in text for token in address_tokens) and not self.menu_service.find_item_by_name(text)

    def _extract_preferences(self, text: str) -> dict[str, list[str] | int]:
        options: list[str] = []
        avoid: list[str] = []
        if "不辣" in text or "不要辣" in text:
            options.append("不辣")
        if "少辣" in text:
            options.append("少辣")
        if "微辣" in text:
            options.append("微辣")
        if "大份" in text:
            options.append("大份")
        if "小份" in text or "不要太撑" in text:
            options.append("小份")
        if "加蛋" in text:
            options.append("加蛋")
        if "加青菜" in text:
            options.append("加青菜")
        if "不要香菜" in text or "不香菜" in text:
            options.append("不要香菜")
            avoid.append("香菜")
        if "不要葱" in text or "不葱" in text:
            options.append("不要葱")
            avoid.append("葱")
        if "去冰" in text:
            options.append("去冰")
        if "少冰" in text:
            options.append("少冰")
        if "冰" in text and "少冰" not in text and "去冰" not in text:
            options.append("冰")
        if "清淡" in text:
            options.append("清淡")
        if "不要太油" in text or "不太油" in text:
            options.append("不要太油")
        if "不吃牛肉" in text or ("不要牛肉" in text and "牛肉饭" not in text):
            avoid.append("牛肉")
        result: dict[str, list[str] | int] = {}
        if options:
            result["options"] = list(dict.fromkeys(options))
        if avoid:
            result["avoid"] = list(dict.fromkeys(avoid))
        if budget := self._extract_budget(text):
            result["budget"] = budget
        return result

    def _extract_item_specs(self, text: str, items: list) -> list[dict]:
        specs = []
        for index, item in enumerate(items):
            start = text.find(item.name)
            next_start = text.find(items[index + 1].name) if index + 1 < len(items) else len(text)
            segment = text[start:next_start] if start >= 0 else text
            specs.append(
                {
                    "item_name": item.name,
                    "quantity": self._extract_quantity(segment),
                    "unit": self._extract_unit(segment),
                    "options": self._extract_preferences(segment).get("options", []),
                }
            )
        return specs

    def _extract_option_name(self, text: str) -> str | None:
        for option in OPTION_TOKENS:
            if option in text:
                return "不辣" if option == "不要辣" else option
        return None

    def _extract_ingredient(self, text: str) -> str | None:
        for ingredient in ["香菜", "鸡蛋", "牛肉", "花生", "葱"]:
            if ingredient in text:
                return ingredient
        return None

    def _extract_allergen(self, text: str) -> str | None:
        for allergen in ["花生", "鸡蛋", "牛肉", "麸质"]:
            if allergen in text:
                return allergen
        return None

    def _extract_budget(self, text: str) -> int | None:
        match = re.search(r"(\d+)元?以内", text)
        if match:
            return int(match.group(1))
        return None

    def _extract_quantity(self, text: str) -> int:
        match = re.search(r"(\d+)(份|个|瓶|杯)?", text)
        if match:
            return int(match.group(1))
        for token, value in CHINESE_NUMBERS.items():
            if token in text:
                return value
        return 1

    def _extract_unit(self, text: str) -> str | None:
        for unit in ["份", "个", "瓶", "杯"]:
            if unit in text:
                return unit
        return None

    def _extract_phone(self, text: str) -> str | None:
        match = re.search(r"1[3-9]\d{9}", text)
        return match.group(0) if match else None

    def _extract_address(self, text: str, noise_tokens: list[str]) -> str | None:
        address = text
        for token in sorted(noise_tokens, key=len, reverse=True):
            address = address.replace(token, "")
        address = address.strip()
        if address in {"", "这个地址", "外卖", "配送", "地址", "这里"}:
            return None
        return address
