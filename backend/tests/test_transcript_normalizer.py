import pytest

from app.voice.transcript_normalizer import normalize_ordering_voice_transcript


MENU_ITEMS = ["牛肉饭", "黑椒牛肉饭", "鸡腿饭", "可乐"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("黑胶牛肉饭吧", "黑椒牛肉饭吧"),
        ("黑角牛肉饭", "黑椒牛肉饭"),
        ("牛肉反", "牛肉饭"),
        ("机腿饭", "鸡腿饭"),
    ],
)
def test_menu_item_corrections_are_conservative(source: str, expected: str) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS)

    assert result.normalized_text == expected
    assert result.original_text == source
    assert result.changed is True
    assert "menu_item_correction" in result.reasons
    assert result.corrections
    assert 0 < result.confidence <= 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("我要一分鸡腿饭", "我要一份鸡腿饭"),
        ("来两分牛肉饭", "来两份牛肉饭"),
        ("再来亿份", "再来一份"),
        ("在来一份", "再来一份"),
    ],
)
def test_quantity_unit_and_repeat_corrections(source: str, expected: str) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS)

    assert result.normalized_text == expected
    assert result.changed is True
    assert result.reasons
    assert result.corrections


@pytest.mark.parametrize(
    ("source", "context", "expected"),
    [
        ("不要啦", {}, "不要了"),
        ("确认一下", {}, "确认"),
        ("可以了", {"current_order_count": 1}, "确认"),
        ("就这些", {"current_order_count": 1}, "确认"),
        ("陪送", {}, "配送"),
    ],
)
def test_action_corrections(source: str, context: dict, expected: str) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS, context=context)

    assert result.normalized_text == expected
    assert result.changed is True


@pytest.mark.parametrize(
    "source",
    [
        "不要辣",
        "不要辣椒",
        "不要放辣椒",
        "不要太辣",
        "不要香菜",
        "不要葱",
        "不要姜",
        "不要蒜",
        "今天不想吃辣",
        "我自己看看",
        "我自己选",
        "我的地址是牛肉街28号",
        "我的地址是牛肉街 28 号",
        "电话是一三八二八二八二八二八",
        "普通聊天文本",
        "牛肉",
    ],
)
def test_negative_cases_keep_original_text(source: str) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS, context={"current_order_count": 0})

    assert result.normalized_text == source
    assert result.changed is False
    assert result.reasons == []
    assert result.corrections == []


@pytest.mark.parametrize("source", ["可以了", "就这些"])
def test_confirm_like_phrases_need_existing_order(source: str) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS, context={"current_order_count": 0})

    assert result.normalized_text == source
    assert result.changed is False


@pytest.mark.parametrize("source", ["我自己看看", "我自己来", "这个我自己选"])
def test_self_mentions_are_not_pickup_without_fulfillment_context(source: str) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS)

    assert result.normalized_text == source
    assert result.changed is False


def test_self_can_be_pickup_in_fulfillment_context() -> None:
    result = normalize_ordering_voice_transcript(
        "自己",
        menu_items=MENU_ITEMS,
        context={"last_question_intent": "provide_fulfillment_slot"},
    )

    assert result.normalized_text == "自取"
    assert result.changed is True
    assert "pickup_context" in result.reasons


def test_metadata_describes_changed_result() -> None:
    result = normalize_ordering_voice_transcript("黑角牛肉饭", menu_items=MENU_ITEMS)

    assert result.original_text == "黑角牛肉饭"
    assert result.normalized_text == "黑椒牛肉饭"
    assert result.changed is True
    assert result.reasons == ["menu_item_correction"]
    assert result.corrections == [{"from": "黑角牛肉饭", "to": "黑椒牛肉饭", "reason": "explicit_menu_asr"}]
    assert result.confidence == pytest.approx(0.96)


@pytest.mark.parametrize("source", [None, "", "   ", "，！？；、"])
def test_empty_and_punctuation_inputs_are_stable(source: str | None) -> None:
    result = normalize_ordering_voice_transcript(source, menu_items=MENU_ITEMS)

    assert result.changed is False
    assert result.reasons == []
    assert result.corrections == []
    assert result.confidence == 1.0
    assert isinstance(result.original_text, str)
    assert result.original_text == result.normalized_text


def test_exact_menu_item_is_not_rewritten() -> None:
    result = normalize_ordering_voice_transcript("黑椒牛肉饭", menu_items=MENU_ITEMS)

    assert result.normalized_text == "黑椒牛肉饭"
    assert result.changed is False
