from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.menu_service import MenuService
    from app.state.session_state import SessionState


PUNCTUATION_RE = re.compile(r"[\s，,。？?！!；;、：:]")
QUESTION_MARKERS = ("?", "？", "吗", "啥", "什么", "多少", "多久", "有没有", "能不能", "能送")
UNIT_TOKENS = ("份儿", "份", "个", "瓶", "杯", "碗")
CHINESE_NUMBERS = {
    "零": 0,
    "一": 1,
    "一个": 1,
    "一份": 1,
    "一瓶": 1,
    "一杯": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "两个": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
CATEGORY_GROUPS = {
    "主食": ["饭类", "面类"],
    "正餐": ["饭类", "面类"],
    "吃的": ["饭类", "面类", "小吃"],
    "喝的": ["饮品"],
}
OPTION_ALIASES = [
    ("不辣", ("不辣", "不要辣", "别辣")),
    ("少辣", ("少辣",)),
    ("微辣", ("微辣",)),
    ("中辣", ("中辣",)),
    ("加辣", ("加辣", "重口")),
    ("不要香菜", ("不要香菜", "不香菜")),
    ("不要葱", ("不要葱", "不葱")),
    ("不要太油", ("不要太油", "别太油", "不要太腻", "不太油")),
    ("清淡", ("清淡", "舒服点", "吃舒服", "垫垫肚子")),
    ("热乎", ("热乎", "暖和")),
    ("有汤", ("有汤",)),
    ("大份", ("大份", "大的")),
    ("小份", ("小份", "小份的", "不要太撑", "一个人吃")),
    ("加蛋", ("加蛋",)),
    ("加青菜", ("加青菜",)),
    ("去冰", ("去冰",)),
    ("少冰", ("少冰",)),
    ("冰", ("冰",)),
    ("快", ("快点", "快一点", "出餐快", "赶时间", "马上")),
    ("便宜", ("便宜", "实惠", "不贵", "性价比")),
    ("管饱", ("管饱", "顶饱")),
    ("下饭", ("下饭", "开胃")),
]
AVOID_ALIASES = [
    ("牛肉", ("不吃牛肉", "不要牛肉", "不含牛肉")),
    ("鸡蛋", ("不吃鸡蛋", "不要鸡蛋")),
    ("香菜", ("不要香菜", "不香菜")),
    ("葱", ("不要葱", "不葱")),
    ("花生", ("花生过敏", "对花生过敏")),
]
RANKING_TOKENS = (
    "最好吃",
    "哪个推荐",
    "比较好",
    "靠谱",
    "稳一点",
    "不踩雷",
    "卖得好",
    "受欢迎",
    "招牌",
    "好喝",
    "新手点",
    "闭眼点",
    "帮我选",
    "你觉得哪个好",
)


def normalize_text(text: str | None) -> str:
    return PUNCTUATION_RE.sub("", (text or "").strip())


def parse_chinese_number(token: str | None) -> int | None:
    if not token:
        return None
    token = normalize_text(token)
    if token.isdigit():
        return int(token)
    if token in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[token]
    for key in sorted(CHINESE_NUMBERS, key=len, reverse=True):
        if key in token:
            return CHINESE_NUMBERS[key]
    return None


def parse_quantity(text: str | None) -> int:
    compact = normalize_text(text)
    if match := re.search(r"(\d+)\s*(?:份儿|份|个|瓶|杯|碗)?", text or ""):
        return int(match.group(1))
    if match := re.search(r"([一二两俩三四五六七八九十])(?:份儿|份|个|瓶|杯|碗)", compact):
        return parse_chinese_number(match.group(1)) or 1
    if match := re.search(r"(?:来|加|再来|改成)([一二两俩三四五六七八九十])", compact):
        return parse_chinese_number(match.group(1)) or 1
    if "来俩" in compact:
        return 2
    return 1


def parse_unit(text: str | None) -> str | None:
    compact = normalize_text(text)
    for unit in UNIT_TOKENS:
        if unit in compact:
            return "份" if unit == "份儿" else unit
    return None


def parse_quantity_each(text: str | None) -> int:
    compact = normalize_text(text)
    if match := re.search(r"(?:各|都来|每样|每种)([一二两俩三四五六七八九十\d]+)", compact):
        return parse_chinese_number(match.group(1)) or parse_quantity(match.group(1))
    return parse_quantity(compact)


def detect_question_features(text: str | None) -> dict[str, Any]:
    compact = normalize_text(text)
    return {"is_question": any(marker in compact for marker in QUESTION_MARKERS)}


def detect_category_group_query(text: str | None) -> dict[str, Any] | None:
    compact = normalize_text(text)
    for group, categories in CATEGORY_GROUPS.items():
        if group in compact:
            return {"group": group, "categories": categories}
    if "喝" in compact and ("有啥" in compact or "有什么" in compact):
        return {"group": "喝的", "categories": ["饮品"]}
    return None


def detect_subjective_ranking_query(text: str | None, menu_service: "MenuService") -> dict[str, Any]:
    compact = normalize_text(text)
    is_ranking = any(token in compact for token in RANKING_TOKENS)
    category = menu_service.find_category_by_alias(compact)
    group = detect_category_group_query(compact)
    return {
        "is_ranking": is_ranking,
        "category": category,
        "category_group": group["group"] if group else None,
        "categories": group["categories"] if group else ([category] if category else []),
        "sales_claim_requested": any(token in compact for token in ["卖得好", "受欢迎", "最受欢迎", "销量"]),
    }


def extract_preferences(text: str | None) -> dict[str, Any]:
    compact = normalize_text(text)
    options: list[str] = []
    avoid: list[str] = []
    for canonical, aliases in OPTION_ALIASES:
        if any(alias in compact for alias in aliases):
            if canonical == "冰" and ("少冰" in options or "去冰" in options):
                continue
            options.append(canonical)
    for canonical, aliases in AVOID_ALIASES:
        if any(alias in compact for alias in aliases):
            avoid.append(canonical)

    result: dict[str, Any] = {}
    if options:
        result["options"] = list(dict.fromkeys(options))
    if avoid:
        result["avoid"] = list(dict.fromkeys(avoid))
    if budget := _extract_budget(compact):
        result["budget"] = budget
    return result


def extract_multiple_items(text: str | None, menu_service: "MenuService") -> list[dict[str, Any]]:
    compact = normalize_text(text)
    items = menu_service.find_items_in_text(compact)
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        start = _find_item_position(compact, item)
        next_start = _find_item_position(compact, items[index + 1]) if index + 1 < len(items) else len(compact)
        previous = items[index - 1] if index > 0 else None
        previous_boundary = _find_item_position(compact, previous) + len(previous.name) if previous else 0
        segment_start = _segment_start(compact, start, previous_boundary)
        segment = compact[segment_start:next_start] if start >= 0 else compact
        preferences = extract_preferences(segment)
        specs.append(
            {
                "item_name": item.name,
                "quantity": parse_quantity(segment),
                "unit": parse_unit(segment),
                "options": preferences.get("options", []),
            }
        )
    return specs


def extract_address_candidate(text: str | None) -> str | None:
    compact = normalize_text(text)
    if not compact:
        return None
    for marker in ["配送到", "外卖到", "送到", "到"]:
        if marker in compact:
            compact = compact[compact.rfind(marker) :]
            break
    address = compact
    noise_tokens = [
        "配送到",
        "外卖到",
        "送到",
        "到",
        "配送费多少",
        "外卖费多少",
        "要送多久",
        "送多久",
        "要多久",
        "多久能送到",
        "多久到",
        "能送到吗",
        "能配送吗",
        "能送吗",
        "配送",
        "外卖",
    ]
    for token in sorted(noise_tokens, key=len, reverse=True):
        address = address.replace(token, "")
    if address in {"", "这个地址", "这里", "地址"}:
        return None
    return address


def detect_composite_intent(text: str | None, menu_service: "MenuService") -> dict[str, Any] | None:
    compact = normalize_text(text)
    children: list[dict[str, Any]] = []

    delivery_child = _detect_delivery_child(compact)
    food_specs = extract_multiple_items(compact, menu_service)
    category_child = _detect_category_bulk_child(compact, menu_service)

    if category_child:
        children.append(category_child)
    elif len(food_specs) >= 2 or (food_specs and delivery_child):
        for spec in food_specs:
            children.append(
                {
                    "intent": "order_food",
                    "confidence": 0.93,
                    "source": "rule",
                    "is_question": False,
                    "should_mutate_order": True,
                    "entities": {"item_name": spec["item_name"], "quantity": spec["quantity"], "unit": spec["unit"]},
                    "preferences": {"options": spec.get("options", [])} if spec.get("options") else {},
                    "target": None,
                    "raw": spec["item_name"],
                }
            )
    if delivery_child:
        children.append(delivery_child)

    if len(children) < 2:
        return None
    return {"intent": "composite_intent", "children": _sort_composite_children(children)}


def detect_conditional_order(text: str | None, menu_service: "MenuService") -> dict[str, Any] | None:
    compact = normalize_text(text)
    if not any(token in compact for token in ["如果", "要是", "的话", "有的话", "不行就", "能送到的话"]):
        return None
    item = menu_service.find_item_by_name(compact)
    if not item:
        return None

    if "多少钱" in compact or "不贵" in compact:
        threshold = _extract_budget(compact) or 30
        return {
            "type": "conditional_order",
            "condition": {"type": "price_threshold", "operator": "<=", "threshold": threshold},
            "fact_result": {"item_name": item.name, "price": item.price, "within_threshold": item.price <= threshold},
            "proposed_action": {
                "intent": "order_food",
                "entities": {"item_name": item.name, "quantity": parse_quantity(compact), "unit": parse_unit(compact)},
                "preferences": extract_preferences(compact),
            },
            "requires_confirmation": True,
        }
    if "不辣" in compact or "不辣就" in compact:
        supports = "不辣" in item.options
        return {
            "type": "conditional_order",
            "condition": {"type": "option_supported", "option": "不辣"},
            "fact_result": {"item_name": item.name, "supports": supports},
            "proposed_action": {
                "intent": "order_food",
                "entities": {"item_name": item.name, "quantity": parse_quantity(compact), "unit": parse_unit(compact)},
                "preferences": {"options": ["不辣"]},
            },
            "requires_confirmation": True,
        }
    if "有" in compact:
        available = bool(item and item.available)
        return {
            "type": "conditional_order",
            "condition": {"type": "availability"},
            "fact_result": {"item_name": item.name, "available": available},
            "proposed_action": {
                "intent": "order_food",
                "entities": {"item_name": item.name, "quantity": parse_quantity(compact), "unit": parse_unit(compact)},
                "preferences": extract_preferences(compact),
            },
            "requires_confirmation": True,
        }
    return None


def resolve_context_reference(text: str | None, state: "SessionState") -> dict[str, Any]:
    compact = normalize_text(text)
    index = _reference_to_index(compact)
    if ("地址" in compact or "这里" in compact) and (
        state.pending_delivery_address_candidate or state.official_delivery_address or state.last_address_mention
    ):
        address = (
            state.pending_delivery_address_candidate.normalized
            if state.pending_delivery_address_candidate
            else state.official_delivery_address or state.last_address_mention
        )
        return {"kind": "address", "address": address}
    if state.last_recommendations and (index is not None or compact in {"就这个", "要这个"}):
        return {"kind": "recommendation", "index": 0 if index is None else index}
    if state.current_order and (index is not None or "刚才那个" in compact or "这个" in compact or "那个" in compact):
        resolved_index = index if index is not None else len(state.current_order) - 1
        return {"kind": "order_item", "index": resolved_index, "item_name": state.current_order[resolved_index].name}
    if state.last_mentioned_category and ("这些" in compact or "那些" in compact):
        return {"kind": "category", "category": state.last_mentioned_category}
    return {"kind": "unresolved"}


def _extract_budget(text: str) -> int | None:
    if match := re.search(r"(\d+)元?以内", text):
        return int(match.group(1))
    if match := re.search(r"(\d+)以内", text):
        return int(match.group(1))
    return None


def _find_item_position(text: str, item: Any) -> int:
    positions = [text.find(name) for name in [item.name, *item.aliases] if name and name in text]
    return min(positions) if positions else -1


def _segment_start(text: str, item_start: int, previous_boundary: int = 0) -> int:
    if item_start <= 0:
        return 0
    separators = [text.rfind(token, previous_boundary, item_start) for token in ["再来", "来", "和", "加", "配"]]
    return max([pos for pos in separators if pos >= 0], default=item_start)


def _detect_delivery_child(text: str) -> dict[str, Any] | None:
    if "配送费" in text or "外卖费" in text or _looks_like_delivery_fee_question(text):
        return _delivery_child("ask_delivery_fee", text, "fee_question")
    if any(token in text for token in ["送多久", "要多久", "配送要多久", "外卖多久", "多久能送到", "多久到"]):
        return _delivery_child("ask_delivery_eta", text, "eta_question")
    if any(token in text for token in ["能送到", "能送", "能配送"]):
        return _delivery_child("ask_deliverability", text, "deliverability_question")
    return None


def _delivery_child(intent: str, text: str, source: str) -> dict[str, Any]:
    address = extract_address_candidate(text)
    return {
        "intent": intent,
        "confidence": 0.96,
        "source": "rule",
        "is_question": True,
        "should_mutate_order": False,
        "entities": {"address": address} if address else {},
        "preferences": {},
        "target": None,
        "candidate_source": source,
        "raw": text,
    }


def _detect_category_bulk_child(text: str, menu_service: "MenuService") -> dict[str, Any] | None:
    category = menu_service.find_category_by_alias(text)
    group = detect_category_group_query(text)
    has_bulk = any(token in text for token in ["各来", "都来", "每样", "每种", "都要"])
    if not has_bulk or "推荐" in text or any(marker in text for marker in ["有什么", "有啥", "有吗"]):
        return None
    if group and group["group"] in {"主食", "吃的"} and not category:
        return {
            "intent": "order_category_group_items",
            "confidence": 0.9,
            "source": "rule",
            "is_question": False,
            "should_mutate_order": True,
            "entities": {"category_group": group["group"], "categories": group["categories"], "quantity_each": parse_quantity_each(text), "unit": parse_unit(text)},
            "preferences": {},
            "target": group["group"],
            "raw": text,
        }
    if category:
        return {
            "intent": "order_category_items",
            "confidence": 0.94,
            "source": "rule",
            "is_question": False,
            "should_mutate_order": True,
            "entities": {"category": category, "quantity_each": parse_quantity_each(text), "unit": parse_unit(text)},
            "preferences": {},
            "target": category,
            "raw": text,
        }
    return None


def _looks_like_delivery_fee_question(text: str) -> bool:
    address_tokens = ("到", "送到", "学校", "大学", "校区", "校园", "东门", "北门", "宿舍", "楼下")
    return "多少钱" in text and any(token in text for token in address_tokens)


def _sort_composite_children(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {
        "ask_menu": 1,
        "ask_category": 1,
        "ask_price": 1,
        "ask_option": 1,
        "ask_availability": 1,
        "order_category_items": 2,
        "order_category_group_items": 2,
        "order_food": 2,
        "order_multiple_items": 2,
        "ask_delivery_eta": 3,
        "ask_delivery_fee": 3,
        "ask_deliverability": 3,
        "provide_fulfillment_slot": 4,
        "provide_delivery_address": 4,
        "provide_phone": 4,
        "confirm": 5,
        "cancel": 5,
    }
    return sorted(children, key=lambda child: order.get(child["intent"], 99))


def _reference_to_index(text: str) -> int | None:
    if any(token in text for token in ["第一个", "第1个"]):
        return 0
    if any(token in text for token in ["第二个", "第2个"]):
        return 1
    if any(token in text for token in ["第三个", "第3个"]):
        return 2
    return None
