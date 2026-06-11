from app.services.delivery_service import DeliveryService
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.state.session_state import OrderItem, SessionState


def test_menu_service_category_and_item_helpers():
    menu = MenuService()

    snacks = menu.get_available_items_by_category("小吃")
    assert [item.name for item in snacks] == ["酸辣土豆丝", "鸡米花"]
    assert menu.find_category_by_alias("有啥喝的") == "饮品"
    assert [item.name for item in menu.find_items_in_text("鸡腿饭一份，可乐两瓶")] == ["鸡腿饭", "可乐"]
    assert menu.get_item_price("鸡腿饭") == 26
    assert menu.supports_option("鸡腿饭", "不辣") is True


def test_menu_service_budget_preference_and_ingredients():
    menu = MenuService()

    under_30 = menu.get_items_under_budget(30)
    assert "鸡腿饭" in [item.name for item in under_30]
    assert all(item.price <= 30 for item in under_30)
    no_beef = menu.find_items_by_tags(avoid=["牛肉"])
    assert all("牛肉" not in item.name and "牛肉" not in item.tags for item in no_beef)
    assert "鸡腿" in menu.get_ingredients("鸡腿饭")
    assert "花生" in menu.get_allergen_warnings("宫保鸡丁饭")


def test_menu_service_recommendation_metadata_and_category_groups():
    menu = MenuService()

    chicken = menu.find_item_by_name("鸡腿饭")
    assert chicken.recommended_score > 0
    assert chicken.recommend_reason
    assert chicken.prep_speed in {"fast", "normal", "slow"}
    assert chicken.taste_profile
    assert chicken.portion in {"small", "medium", "large"}

    assert menu.find_category_group_by_alias("主食有什么") == "主食"
    assert menu.get_categories_by_group("主食") == ["饭类", "面类"]
    group_items = menu.get_items_by_category_group("主食")
    assert {item.category for item in group_items} == {"饭类", "面类"}

    ranked = menu.get_ranked_recommendations(category="饭类", limit=2)
    assert len(ranked) == 2
    assert ranked[0].recommended_score >= ranked[1].recommended_score
    assert not hasattr(ranked[0], "sales_count")


def test_order_service_batch_update_remove_replace_and_total():
    menu = MenuService()
    service = OrderService()
    state = SessionState()

    state.current_order = service.add_items(
        state,
        [
            {"item": menu.find_item_by_name("鸡腿饭"), "quantity": 1, "options": ["不辣"], "unit": "份"},
            {"item": menu.find_item_by_name("可乐"), "quantity": 2, "options": ["冰"], "unit": "瓶"},
        ],
    )
    assert len(state.current_order) == 2
    assert service.total_price(state) == 38

    updated, ok = service.update_quantity(state, "可乐", 3)
    state.current_order = updated
    assert ok is True
    assert next(item for item in state.current_order if item.name == "可乐").quantity == 3

    replaced, ok = service.replace_item(state, "鸡腿饭", menu.find_item_by_name("番茄鸡蛋面"), quantity=1, options=["加蛋"])
    state.current_order = replaced
    assert ok is True
    assert "番茄鸡蛋面" in [item.name for item in state.current_order]

    removed, count = service.remove_category(state, "饮品")
    assert count == 1
    assert all(item.category != "饮品" for item in removed)


def test_delivery_service_address_phone_and_references():
    delivery = DeliveryService()

    assert delivery.normalize_address("到中山大学南校园") == "中山大学南校园"
    assert delivery.is_valid_phone("13812345678") is True
    assert delivery.extract_phone("电话 13812345678") == "13812345678"
    assert delivery.resolve_address_reference("这个地址", pending="中山大学南校园", official=None, last=None) == "中山大学南校园"
    assert delivery.estimate_eta("中山大学南校园") == 32
    assert delivery.estimate_fee("中山大学南校园") == 5
