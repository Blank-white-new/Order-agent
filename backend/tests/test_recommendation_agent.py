from .conftest import assert_trace_basics, send


def test_general_recommendation_variants(orchestrator):
    for message in ["推荐", "不知道吃啥", "你看着办"]:
        result = send(orchestrator, message)
        assert_trace_basics(result, agent="RecommendationAgent", handler="ask_recommendation", intent="ask_recommendation")
        assert len(result["state"]["last_recommendations"]) >= 2
        assert "没太理解" not in result["response"]


def test_recommendation_by_category(orchestrator):
    result = send(orchestrator, "小吃推荐一下")

    assert_trace_basics(result, agent="RecommendationAgent", handler="ask_recommendation_by_category", intent="ask_recommendation_by_category")
    assert all(item["category"] == "小吃" for item in result["state"]["last_recommendations"])
    assert "鸡米花" in result["response"] or "酸辣土豆丝" in result["response"]


def test_recommendation_by_preference_budget_and_speed(orchestrator):
    result = send(orchestrator, "来个清淡点的")
    assert_trace_basics(result, agent="RecommendationAgent", handler="ask_recommendation_by_preference", intent="ask_recommendation_by_preference")
    assert "番茄鸡蛋面" in [item["name"] for item in result["state"]["last_recommendations"]]

    result = send(orchestrator, "30 元以内推荐")
    assert_trace_basics(result, agent="RecommendationAgent", handler="ask_recommendation_by_budget", intent="ask_recommendation_by_budget")
    assert all(item["price"] <= 30 for item in result["state"]["last_recommendations"])

    result = send(orchestrator, "快一点的")
    assert_trace_basics(result, agent="RecommendationAgent", handler="ask_recommendation_by_speed", intent="ask_recommendation_by_speed")
    assert result["state"]["last_recommendations"]


def test_recommendation_refresh(orchestrator):
    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "换一个", state)

    assert_trace_basics(result, agent="RecommendationAgent", handler="ask_recommendation", intent="ask_recommendation")
    assert result["state"]["last_recommendations"]


def test_ranked_recommendation_by_category_without_fake_sales(orchestrator):
    result = send(orchestrator, "饭类哪个最好吃")

    assert_trace_basics(
        result,
        agent="RecommendationAgent",
        handler="ask_recommendation_by_category_ranked",
        intent="ask_recommendation_by_category_ranked",
    )
    assert all(item["category"] == "饭类" for item in result["state"]["last_recommendations"])
    assert "鸡腿饭" in result["response"]
    assert "销量第一" not in result["response"]
    assert "最畅销" not in result["response"]


def test_popularity_wording_does_not_invent_sales(orchestrator):
    result = send(orchestrator, "哪个卖得好")

    assert_trace_basics(
        result,
        agent="RecommendationAgent",
        handler="ask_recommendation_by_category_ranked",
        intent="ask_recommendation_by_category_ranked",
    )
    assert "没有真实销量数据" in result["response"]
    assert "销量第一" not in result["response"]
    assert "卖得最好" not in result["response"]
