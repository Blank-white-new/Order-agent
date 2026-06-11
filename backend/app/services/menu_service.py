from __future__ import annotations

from app.models.schemas import MenuItem, dump_model


class MenuService:
    def __init__(self) -> None:
        self._items = [
            MenuItem(
                id="beef_rice",
                name="牛肉饭",
                category="饭类",
                price=28,
                tags=["牛肉", "饭", "主食"],
                spicy_level=0,
                options=["不辣", "少辣", "大份", "标准"],
                aliases=["牛肉盖饭"],
                description="经典牛肉饭。",
                ingredients=["牛肉", "米饭", "青菜"],
                allergens=[],
                recommended_score=8.1,
                recommend_reason="经典主食，口味稳。",
                prep_speed="normal",
                taste_profile=["咸香", "管饱"],
                portion="large",
            ),
            MenuItem(
                id="black_pepper_beef_rice",
                name="黑椒牛肉饭",
                category="饭类",
                price=30,
                tags=["牛肉", "黑椒", "饭", "主食"],
                spicy_level=1,
                options=["不辣", "少辣", "大份", "标准"],
                aliases=["黑椒饭"],
                description="黑椒风味牛肉饭。",
                ingredients=["牛肉", "黑椒汁", "米饭", "青菜"],
                allergens=[],
                recommended_score=8.0,
                recommend_reason="黑椒香味更重，适合想吃下饭口味。",
                prep_speed="normal",
                taste_profile=["黑椒", "下饭"],
                portion="large",
            ),
            MenuItem(
                id="chicken_leg_rice",
                name="鸡腿饭",
                category="饭类",
                price=26,
                tags=["鸡肉", "饭", "主食"],
                spicy_level=1,
                options=["不辣", "少辣", "微辣", "大份", "加饭", "标准"],
                aliases=["鸡腿盖饭"],
                description="鸡腿配米饭，可做不辣。",
                ingredients=["鸡腿", "米饭", "青菜"],
                allergens=[],
                recommended_score=9.1,
                recommend_reason="可做不辣，价格适中，比较适合大多数人。",
                prep_speed="normal",
                taste_profile=["咸香", "下饭"],
                portion="large",
            ),
            MenuItem(
                id="kung_pao_chicken_rice",
                name="宫保鸡丁饭",
                category="饭类",
                price=29,
                tags=["鸡肉", "饭", "微辣", "主食"],
                spicy_level=2,
                options=["不辣", "少辣", "微辣", "加饭", "标准"],
                aliases=["宫保饭"],
                description="宫保鸡丁配米饭。",
                ingredients=["鸡丁", "花生", "米饭", "辣椒"],
                allergens=["花生"],
                recommended_score=8.4,
                recommend_reason="酸甜微辣，下饭感强。",
                prep_speed="normal",
                taste_profile=["酸甜", "微辣", "下饭"],
                portion="large",
            ),
            MenuItem(
                id="tomato_egg_noodles",
                name="番茄鸡蛋面",
                category="面类",
                price=24,
                tags=["面", "素", "清淡", "热乎", "有汤", "主食"],
                spicy_level=0,
                options=["不辣", "加面", "加蛋", "加青菜", "不要葱", "标准"],
                aliases=["番茄面", "鸡蛋面"],
                description="番茄鸡蛋汤面。",
                ingredients=["番茄", "鸡蛋", "面条", "葱"],
                allergens=["鸡蛋"],
                recommended_score=8.8,
                recommend_reason="清淡热乎，有汤，适合想吃舒服点。",
                prep_speed="normal",
                taste_profile=["清淡", "热乎", "有汤"],
                portion="medium",
            ),
            MenuItem(
                id="beef_noodles",
                name="牛肉面",
                category="面类",
                price=28,
                tags=["牛肉", "面", "有汤", "热乎", "主食"],
                spicy_level=1,
                options=["不辣", "少辣", "加面", "不要香菜", "不要葱", "标准"],
                aliases=["牛肉汤面"],
                description="牛肉汤面。",
                ingredients=["牛肉", "面条", "香菜", "葱"],
                allergens=[],
                recommended_score=8.2,
                recommend_reason="热汤主食，分量比较足。",
                prep_speed="normal",
                taste_profile=["热乎", "有汤", "管饱"],
                portion="large",
            ),
            MenuItem(
                id="sour_spicy_potato",
                name="酸辣土豆丝",
                category="小吃",
                price=18,
                tags=["素", "酸辣", "小吃"],
                spicy_level=2,
                options=["不辣", "少辣", "微辣", "标准"],
                aliases=["土豆丝"],
                description="酸辣口土豆丝。",
                ingredients=["土豆", "辣椒", "醋"],
                allergens=[],
                recommended_score=7.9,
                recommend_reason="酸辣开胃，小吃里更清爽。",
                prep_speed="fast",
                taste_profile=["酸辣", "开胃"],
                portion="medium",
            ),
            MenuItem(
                id="popcorn_chicken",
                name="鸡米花",
                category="小吃",
                price=16,
                tags=["鸡肉", "小吃", "快"],
                spicy_level=0,
                options=["不辣", "番茄酱", "不要番茄酱", "标准"],
                aliases=["炸鸡米花"],
                description="小份炸鸡米花。",
                ingredients=["鸡肉", "面包糠"],
                allergens=["麸质"],
                recommended_score=8.3,
                recommend_reason="出餐快，适合加一份小吃。",
                prep_speed="fast",
                taste_profile=["香脆", "快"],
                portion="small",
            ),
            MenuItem(
                id="cola",
                name="可乐",
                category="饮品",
                price=6,
                tags=["饮品", "汽水", "快"],
                spicy_level=0,
                options=["常温", "冰", "去冰", "少冰"],
                aliases=["可口可乐"],
                description="罐装可乐。",
                ingredients=["碳酸水", "糖"],
                allergens=[],
                recommended_score=7.6,
                recommend_reason="搭配主食简单直接。",
                prep_speed="fast",
                taste_profile=["清爽", "汽水"],
                portion="small",
            ),
            MenuItem(
                id="sprite",
                name="雪碧",
                category="饮品",
                price=6,
                tags=["饮品", "汽水", "快"],
                spicy_level=0,
                options=["常温", "冰", "去冰", "少冰"],
                aliases=[],
                description="罐装雪碧。",
                ingredients=["碳酸水", "糖"],
                allergens=[],
                recommended_score=7.4,
                recommend_reason="清爽汽水，适合配小吃。",
                prep_speed="fast",
                taste_profile=["清爽", "汽水"],
                portion="small",
            ),
            MenuItem(
                id="lemon_tea",
                name="柠檬茶",
                category="饮品",
                price=8,
                tags=["饮品", "茶", "快"],
                spicy_level=0,
                options=["常温", "冰", "去冰", "少冰", "热的"],
                aliases=["冻柠茶"],
                description="瓶装柠檬茶。",
                ingredients=["茶", "柠檬", "糖"],
                allergens=[],
                recommended_score=7.8,
                recommend_reason="茶味清爽，比汽水更柔和。",
                prep_speed="fast",
                taste_profile=["清爽", "茶"],
                portion="small",
            ),
        ]

    def get_all_categories(self) -> list[str]:
        categories: list[str] = []
        for item in self._items:
            if item.category not in categories:
                categories.append(item.category)
        return categories

    def get_menu_overview(self, exclude_category: str | None = None) -> dict[str, list[MenuItem]]:
        overview: dict[str, list[MenuItem]] = {}
        for item in self._items:
            if not item.available:
                continue
            if exclude_category and item.category == exclude_category:
                continue
            overview.setdefault(item.category, []).append(item)
        return overview

    def get_items_by_category(self, category: str) -> list[MenuItem]:
        return self.get_available_items_by_category(category)

    def get_available_items_by_category(self, category: str) -> list[MenuItem]:
        resolved = self.find_category_by_alias(category) or category
        return [item for item in self._items if item.category == resolved and item.available]

    def find_category_group_by_alias(self, text: str | None) -> str | None:
        if not text:
            return None
        groups = {
            "主食": ["主食", "正餐"],
            "吃的": ["吃的"],
            "喝的": ["喝的"],
        }
        for group, aliases in groups.items():
            if any(alias in text for alias in aliases):
                return group
        return None

    def get_categories_by_group(self, group: str) -> list[str]:
        groups = {
            "主食": ["饭类", "面类"],
            "正餐": ["饭类", "面类"],
            "吃的": ["饭类", "面类", "小吃"],
            "喝的": ["饮品"],
        }
        return groups.get(group, [])

    def get_items_by_category_group(self, group: str) -> list[MenuItem]:
        categories = self.get_categories_by_group(group)
        return [item for item in self._items if item.available and item.category in categories]

    def find_item_by_name(self, text: str | None) -> MenuItem | None:
        if not text:
            return None
        for item in self._items:
            names = [item.name, *item.aliases]
            if any(name and name == text for name in names):
                return item
        matches: list[tuple[int, int, MenuItem]] = []
        for item in self._items:
            names = [item.name, *item.aliases]
            for name in names:
                if name and name in text:
                    matches.append((text.find(name), -len(name), item))
        if matches:
            return sorted(matches, key=lambda match: (match[0], match[1]))[0][2]
        return None

    def find_items_in_text(self, text: str | None) -> list[MenuItem]:
        if not text:
            return []
        matches: list[MenuItem] = []
        positions: list[tuple[int, int, MenuItem]] = []
        for item in self._items:
            names = [item.name, *item.aliases]
            found = [(text.find(name), len(name)) for name in names if name and name in text]
            if found:
                position, length = min(found, key=lambda pair: (pair[0], -pair[1]))
                positions.append((position, length, item))
        occupied: list[range] = []
        for position, length, item in sorted(positions, key=lambda pair: (pair[0], -pair[1])):
            span = range(position, position + length)
            if any(position < existing.stop and position + length > existing.start for existing in occupied):
                continue
            if item.id not in {existing.id for existing in matches}:
                matches.append(item)
                occupied.append(span)
        return matches

    def find_category_by_alias(self, text: str | None) -> str | None:
        if not text:
            return None
        aliases = {
            "饭类": ["饭类", "米饭", "盖饭", "主食", "饭"],
            "面类": ["面类", "面条", "面"],
            "小吃": ["小吃", "零食"],
            "饮品": ["饮品", "饮料", "喝的", "喝", "水", "可乐", "雪碧", "茶"],
        }
        for category, values in aliases.items():
            if any(alias in text for alias in values):
                return category
        return None

    def find_items_by_tags(
        self,
        include: list[str] | None = None,
        avoid: list[str] | None = None,
        category: str | None = None,
    ) -> list[MenuItem]:
        include = include or []
        avoid = avoid or []
        items = [item for item in self._items if item.available]
        if category:
            resolved = self.find_category_by_alias(category) or category
            items = [item for item in items if item.category == resolved]
        if include:
            items = [item for item in items if any(token in item.name or token in item.tags or token in item.ingredients for token in include)]
        if avoid:
            items = [
                item
                for item in items
                if all(token not in item.name and token not in item.tags and token not in item.ingredients for token in avoid)
            ]
        return items

    def find_similar_items(self, preferences: dict | None = None, limit: int = 3) -> list[MenuItem]:
        preferences = preferences or {}
        category = preferences.get("category")
        avoid = preferences.get("avoid", [])
        include: list[str] = []
        options = preferences.get("options", [])
        if "清淡" in options or "清淡点" in options:
            include.append("清淡")
        if "快" in options or "快一点" in options:
            include.append("快")
        candidates = self.find_items_by_tags(include=include, avoid=avoid, category=category)
        if not category:
            candidates = [item for item in candidates if item.category != "饮品"]
        if any(option in {"不辣", "不要辣"} for option in options):
            candidates = [item for item in candidates if item.spicy_level == 0 or "不辣" in item.options]
        budget = preferences.get("budget")
        if budget:
            candidates = [item for item in candidates if item.price <= int(budget)]
        ordered = sorted(candidates, key=lambda item: (-item.recommended_score, item.price))
        return ordered[:limit]

    def get_ranked_recommendations(
        self,
        category: str | None = None,
        categories: list[str] | None = None,
        preferences: dict | None = None,
        limit: int = 3,
    ) -> list[MenuItem]:
        preferences = preferences or {}
        avoid = preferences.get("avoid", [])
        options = preferences.get("options", [])
        items = [item for item in self._items if item.available]
        if category:
            resolved = self.find_category_by_alias(category) or category
            items = [item for item in items if item.category == resolved]
        if categories:
            items = [item for item in items if item.category in categories]
        if avoid:
            items = [
                item
                for item in items
                if all(token not in item.name and token not in item.tags and token not in item.ingredients for token in avoid)
            ]
        if any(option in {"不辣", "不要辣"} for option in options):
            items = [item for item in items if item.spicy_level == 0 or "不辣" in item.options]
        if "清淡" in options:
            items = [item for item in items if "清淡" in item.tags or "清淡" in item.taste_profile or item.spicy_level == 0]
        if "快" in options:
            items = [item for item in items if item.prep_speed == "fast"]
        if budget := preferences.get("budget"):
            items = [item for item in items if item.price <= int(budget)]
        return sorted(items, key=lambda item: (-item.recommended_score, item.price))[:limit]

    def get_items_under_budget(self, budget: int) -> list[MenuItem]:
        return [item for item in self._items if item.available and item.price <= budget]

    def get_item_price(self, name: str) -> int | None:
        item = self.find_item_by_name(name)
        return item.price if item else None

    def get_item_options(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return item.options if item else []

    def supports_option(self, name: str, option: str) -> bool:
        item = self.find_item_by_name(name)
        return bool(item and option in item.options)

    def get_ingredients(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return item.ingredients if item else []

    def get_allergen_warnings(self, name: str) -> list[str]:
        item = self.find_item_by_name(name)
        return item.allergens if item else []

    def all_items_as_dicts(self) -> list[dict]:
        return [dump_model(item) for item in self._items]
