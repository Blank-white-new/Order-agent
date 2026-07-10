from __future__ import annotations

import json

import pytest

from app.services.menu_config_loader import MenuConfigError, load_menu_config, parse_menu_config
from app.services.menu_service import MenuService
from .conftest import send


EXPECTED_MENU_SNAPSHOT = [
    ("beef_rice", "牛肉饭", 28, "饭类", ["牛肉盖饭"], 8.1),
    ("black_pepper_beef_rice", "黑椒牛肉饭", 30, "饭类", ["黑椒饭"], 8.0),
    ("chicken_leg_rice", "鸡腿饭", 26, "饭类", ["鸡腿盖饭"], 9.1),
    ("kung_pao_chicken_rice", "宫保鸡丁饭", 29, "饭类", ["宫保饭"], 8.4),
    ("tomato_egg_noodles", "番茄鸡蛋面", 24, "面类", ["番茄面", "鸡蛋面"], 8.8),
    ("beef_noodles", "牛肉面", 28, "面类", ["牛肉汤面"], 8.2),
    ("sour_spicy_potato", "酸辣土豆丝", 18, "小吃", ["土豆丝"], 7.9),
    ("popcorn_chicken", "鸡米花", 16, "小吃", ["炸鸡米花"], 8.3),
    ("cola", "可乐", 6, "饮品", ["可口可乐"], 7.6),
    ("sprite", "雪碧", 6, "饮品", [], 7.4),
    ("lemon_tea", "柠檬茶", 8, "饮品", ["冻柠茶"], 7.8),
]


def test_default_menu_config_loads_preserved_menu_snapshot():
    loaded = load_menu_config()
    menu = MenuService()

    assert loaded.currency == "CNY"
    assert menu.get_all_categories() == ["饭类", "面类", "小吃", "饮品"]
    assert [
        (item.id, item.name, item.price, item.category, item.aliases, item.recommended_score)
        for item in loaded.items
    ] == EXPECTED_MENU_SNAPSHOT
    assert menu.find_item_by_name("鸡腿饭").price == 26
    assert menu.find_item_by_name("宫保鸡丁").name == "宫保鸡丁饭"
    assert menu.find_item_by_name("黑椒牛肉饭").price == 30
    assert menu.find_item_by_name("可乐").price == 6
    assert menu.find_item_by_name("机腿饭").name == "鸡腿饭"
    assert loaded.safe_match_aliases["chicken_leg_rice"] == ["机腿饭"]


def test_default_menu_config_preserves_recommendation_order():
    menu = MenuService()

    assert [item.name for item in menu.get_ranked_recommendations(category="饭类", limit=4)] == [
        "鸡腿饭",
        "宫保鸡丁饭",
        "牛肉饭",
        "黑椒牛肉饭",
    ]
    assert [item.name for item in menu.get_available_items_by_category("小吃")] == ["酸辣土豆丝", "鸡米花"]


def test_duplicate_item_id_is_rejected():
    config = _valid_config(
        [
            _item("same", "测试饭", 12),
            _item("same", "测试面", 13),
        ]
    )

    with pytest.raises(MenuConfigError, match="Duplicate menu item id"):
        parse_menu_config(config)


def test_missing_name_is_rejected():
    item = _item("test_rice", "测试饭", 12)
    item.pop("name")

    with pytest.raises(MenuConfigError, match="missing required field 'name'"):
        parse_menu_config(_valid_config([item]))


def test_negative_price_is_rejected():
    item = _item("test_rice", "测试饭", -1)

    with pytest.raises(MenuConfigError, match="non-negative integer"):
        parse_menu_config(_valid_config([item]))


@pytest.mark.parametrize("aliases", ["测试别名", [""]])
def test_invalid_aliases_are_rejected(aliases):
    item = _item("test_rice", "测试饭", 12)
    item["aliases"] = aliases

    with pytest.raises(MenuConfigError, match="aliases"):
        parse_menu_config(_valid_config([item]))


def test_alias_conflict_is_rejected():
    config = _valid_config(
        [
            _item("rice_a", "测试饭", 12, aliases=["测试面"]),
            _item("noodle_b", "测试面", 13),
        ]
    )

    with pytest.raises(MenuConfigError, match="conflicts"):
        parse_menu_config(config)


def test_external_menu_config_missing_path_reports_clear_error(monkeypatch, tmp_path):
    missing = tmp_path / "missing-menu.json"
    monkeypatch.setenv("MENU_CONFIG_PATH", str(missing))

    with pytest.raises(MenuConfigError) as exc_info:
        load_menu_config()

    message = str(exc_info.value)
    assert "MENU_CONFIG_PATH" in message
    assert "missing-menu.json" in message
    assert str(tmp_path) not in message


def test_external_menu_config_invalid_json_reports_clear_error(monkeypatch, tmp_path):
    path = tmp_path / "menu.json"
    path.write_text("{", encoding="utf-8")
    monkeypatch.setenv("MENU_CONFIG_PATH", str(path))

    with pytest.raises(MenuConfigError, match="JSON is invalid"):
        load_menu_config()


def test_external_menu_config_can_override_default(monkeypatch, tmp_path):
    path = tmp_path / "menu.json"
    path.write_text(json.dumps(_valid_config([_item("test_noodle", "测试面", 15)]), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MENU_CONFIG_PATH", str(path))

    menu = MenuService()

    assert [item["name"] for item in menu.all_items_as_dicts()] == ["测试面"]
    assert menu.get_item_price("鸡腿饭") is None
    assert menu.get_item_price("测试面") == 15


def test_unavailable_configured_item_is_hidden_from_menu_recommendation_and_ordering(tmp_path):
    path = tmp_path / "menu.json"
    config = _valid_config(
        [
            _item("visible_rice", "可见饭", 12, recommended_score=9.0),
            _item("hidden_rice", "隐藏饭", 1, recommended_score=99.0, available=False),
        ]
    )
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    menu = MenuService(config_path=path)

    assert [item["name"] for item in menu.all_items_as_dicts()] == ["可见饭"]
    assert menu.find_item_by_name("隐藏饭") is None
    assert [item.name for item in menu.get_ranked_recommendations(limit=2)] == ["可见饭"]


def test_config_loaded_menu_supports_ordering_alias_recommendation_modifiers_and_submit(orchestrator):
    ordered = send(orchestrator, "机腿饭两份")
    assert ordered["state"]["current_order"][0]["name"] == "鸡腿饭"
    assert ordered["state"]["current_order"][0]["quantity"] == 2

    updated = send(orchestrator, "鸡腿饭改成三份", ordered["raw_state"])
    assert updated["state"]["current_order"][0]["quantity"] == 3

    modified = send(orchestrator, "鸡腿饭少辣，不要香菜", updated["raw_state"])
    item = modified["state"]["current_order"][0]
    assert item["spicy_level"] == "少辣"
    assert item["exclusions"] == ["香菜"]

    recommended = send(orchestrator, "推荐")
    assert recommended["state"]["last_recommendations"]

    removed = send(orchestrator, "把鸡腿饭删掉", modified["raw_state"])
    assert removed["state"]["current_order"] == []

    submitted_state = send(orchestrator, "来一份鸡腿饭")["raw_state"]
    submitted_state = send(orchestrator, "自取", submitted_state)["raw_state"]
    submitted = send(orchestrator, "确认", submitted_state)
    assert submitted["state"]["submitted"] is True


def _valid_config(items: list[dict]) -> dict:
    return {
        "version": 1,
        "currency": "CNY",
        "categories": [{"name": "测试类", "aliases": ["测试类"], "groups": ["吃的"]}],
        "category_group_aliases": {"吃的": ["吃的"]},
        "items": items,
    }


def _item(
    item_id: str,
    name: str,
    price: int,
    *,
    aliases: list[str] | None = None,
    recommended_score: float = 1.0,
    available: bool = True,
) -> dict:
    return {
        "id": item_id,
        "name": name,
        "category": "测试类",
        "price": price,
        "aliases": aliases or [],
        "recommended_score": recommended_score,
        "available": available,
    }
