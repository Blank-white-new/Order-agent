from __future__ import annotations

from app.models.schemas import Interpretation, dump_model
from app.services.menu_service import MenuService
from app.state.session_state import SessionState


class RecommendationAgent:
    name = "RecommendationAgent"

    def __init__(self, menu_service: MenuService) -> None:
        self.menu_service = menu_service

    def handle(self, interpretation: Interpretation, state: SessionState) -> dict:
        if interpretation.intent == "ask_recommendation_by_category_ranked":
            return self._handle_ranked(interpretation, state)
        preferences = self._merged_preferences(interpretation, state)
        items = self.menu_service.find_similar_items(preferences, limit=3)
        if interpretation.intent == "ask_recommendation" and state.last_recommendations and interpretation.entities.get("refresh"):
            previous = {item["id"] for item in state.last_recommendations}
            alternatives = [item for item in self.menu_service.find_items_by_tags(avoid=preferences.get("avoid", [])) if item.id not in previous]
            items = alternatives[:3] or items
        recommendations = [dump_model(item) for item in items]
        if not items:
            message = "暂时没找到合适的推荐，可以换个偏好试试。"
        else:
            message = "推荐你试试：" + "、".join(f"{item.name}{item.price}元" for item in items) + "。"
        patch = {"last_recommendations": recommendations}
        if preferences.get("avoid") or preferences.get("options"):
            patch["preferences"] = self._updated_state_preferences(state, preferences)
        return {"agent": self.name, "handler": interpretation.intent, "message": message, "patch": patch}

    def _handle_ranked(self, interpretation: Interpretation, state: SessionState) -> dict:
        preferences = self._merged_preferences(interpretation, state)
        categories = interpretation.entities.get("categories") or None
        category = interpretation.entities.get("category") or state.viewed_category
        items = self.menu_service.get_ranked_recommendations(
            category=category,
            categories=categories,
            preferences=preferences,
            limit=3,
        )
        recommendations = [dump_model(item) for item in items]
        if not items:
            message = "暂时没找到合适的推荐，可以换个分类或偏好。"
        else:
            prefix = "我没有真实销量数据，但按推荐标签和口味，我比较推荐：" if interpretation.entities.get("sales_claim_requested") else "我比较推荐："
            message = prefix + "、".join(f"{item.name}{item.price}元（{item.recommend_reason}）" for item in items) + "。"
        patch = {"last_recommendations": recommendations}
        if category:
            patch["viewed_category"] = category
        if interpretation.entities.get("category_group"):
            patch["viewed_category_group"] = interpretation.entities.get("category_group")
        return {"agent": self.name, "handler": interpretation.intent, "message": message, "patch": patch}

    def _merged_preferences(self, interpretation: Interpretation, state: SessionState) -> dict:
        preferences = {key: list(value) for key, value in state.preferences.items()}
        for key, value in interpretation.preferences.items():
            if key in {"avoid", "options"}:
                for token in value:
                    if token not in preferences.setdefault(key, []):
                        preferences[key].append(token)
            else:
                preferences[key] = value
        if category := interpretation.entities.get("category"):
            preferences["category"] = category
        if budget := interpretation.entities.get("budget"):
            preferences["budget"] = budget
        if interpretation.intent == "ask_recommendation_by_speed":
            preferences.setdefault("options", []).append("快")
        return preferences

    def _updated_state_preferences(self, state: SessionState, preferences: dict) -> dict:
        updated = {key: list(value) for key, value in state.preferences.items()}
        for key in ["avoid", "options"]:
            for token in preferences.get(key, []):
                if token not in updated.setdefault(key, []):
                    updated[key].append(token)
        return updated
