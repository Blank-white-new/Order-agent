"""API end-to-end acceptance tests using FastAPI TestClient.

These tests exercise the real /api/chat endpoint with multi-turn conversations,
covering state persistence through session_store.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _sid():
    """Generate a unique session ID to isolate tests."""
    return f"test-{uuid.uuid4().hex[:12]}"


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 1: Question should not order
# ═══════════════════════════════════════════════════════════════════════

def test_api_question_does_not_order(client):
    """'牛肉饭是哪里的牛肉' should not add to order via API."""
    sid = _sid()
    r = client.post("/api/chat", json={"session_id": sid, "message": "牛肉饭是哪里的牛肉"})
    assert r.status_code == 200
    data = r.json()
    assert data["trace"]["fallbackUsed"] is False
    assert data["trace"]["finalIntent"] != "order_food", (
        f"Question should not be order_food, got {data['trace']['finalIntent']}"
    )
    assert data["state"]["current_order"] == []
    assert "牛肉" in data["response"]


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 2: Cancel → reorder → confirm (full chain)
# ═══════════════════════════════════════════════════════════════════════

def test_api_cancel_reorder_full_chain(client):
    """牛肉饭→不要了→鸡腿饭→确认: full API chain, old cleared, new remains."""
    sid = _sid()

    # Turn 1: order beef rice
    r1 = client.post("/api/chat", json={"session_id": sid, "message": "牛肉饭"})
    assert r1.status_code == 200
    s1 = r1.json()["state"]
    assert len(s1["current_order"]) == 1
    assert s1["current_order"][0]["name"] == "牛肉饭"

    # Turn 2: cancel
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "不要了"})
    assert r2.status_code == 200
    s2 = r2.json()["state"]
    assert s2["pending_action"] is not None
    assert s2["pending_action"]["type"] == "confirm_clear_order"
    assert len(s2["current_order"]) == 1  # not cleared yet

    # Turn 3: reorder chicken rice (clears old, adds new)
    r3 = client.post("/api/chat", json={"session_id": sid, "message": "鸡腿饭"})
    assert r3.status_code == 200
    s3 = r3.json()["state"]
    assert s3["pending_action"] is None, "pending must be cleared"
    assert len(s3["current_order"]) == 1, "old order cleared, only new item"
    assert s3["current_order"][0]["name"] == "鸡腿饭"
    assert r3.json()["trace"]["fallbackUsed"] is False

    # Turn 4: confirm (should not trigger old clear, should ask for address)
    r4 = client.post("/api/chat", json={"session_id": sid, "message": "确认"})
    assert r4.status_code == 200
    s4 = r4.json()["state"]
    assert len(s4["current_order"]) == 1, "order must not be cleared"
    assert s4["current_order"][0]["name"] == "鸡腿饭"
    assert s4["submitted"] is False, "should not submit without address"
    assert s4["pending_action"] is None
    resp4 = r4.json()["response"]
    assert "地址" in resp4 or "配送" in resp4 or "自取" in resp4


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 3: Menu context → dish fragment reference
# ═══════════════════════════════════════════════════════════════════════

def test_api_menu_then_dish_fragment_orders(client):
    """有啥饭→黑椒那个: orders 黑椒牛肉饭 via API."""
    sid = _sid()

    r1 = client.post("/api/chat", json={"session_id": sid, "message": "有啥饭"})
    assert r1.status_code == 200
    assert r1.json()["trace"]["fallbackUsed"] is False

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "黑椒那个"})
    assert r2.status_code == 200
    assert r2.json()["trace"]["fallbackUsed"] is False
    assert r2.json()["trace"]["finalIntent"] == "order_food"

    s2 = r2.json()["state"]
    assert len(s2["current_order"]) == 1
    assert s2["current_order"][0]["name"] == "黑椒牛肉饭", (
        f"Expected 黑椒牛肉饭, got {s2['current_order'][0]['name']}"
    )


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 4: Bare "那个" does not order
# ═══════════════════════════════════════════════════════════════════════

def test_api_bare_nage_does_not_order(client):
    """有啥饭→那个: does not order, asks for clarification."""
    sid = _sid()

    r1 = client.post("/api/chat", json={"session_id": sid, "message": "有啥饭"})
    assert r1.status_code == 200

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "那个"})
    assert r2.status_code == 200
    s2 = r2.json()["state"]
    assert len(s2["current_order"]) == 0, (
        f"Bare '那个' must not add items, got {s2['current_order']}"
    )
    # Should not be order_food
    intent = r2.json()["trace"]["finalIntent"]
    assert intent != "order_food", f"Got {intent}, should not be order_food"


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 5: Ambiguous dish fragment lists candidates
# ═══════════════════════════════════════════════════════════════════════

def test_api_ambiguous_fragment_lists_candidates(client):
    """有啥饭→牛肉那个: does not order, lists candidate dishes."""
    sid = _sid()

    r1 = client.post("/api/chat", json={"session_id": sid, "message": "有啥饭"})
    assert r1.status_code == 200

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "牛肉那个"})
    assert r2.status_code == 200
    s2 = r2.json()["state"]
    assert len(s2["current_order"]) == 0, "Must not order on ambiguous fragment"

    resp = r2.json()["response"]
    # Should mention at least two candidates
    candidates_found = sum(
        1 for name in ["牛肉饭", "黑椒牛肉饭", "牛肉面"] if name in resp
    )
    assert candidates_found >= 2, f"Expected >=2 candidates in response: {resp}"


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 6: 就那个 with recommendations asks which
# ═══════════════════════════════════════════════════════════════════════

def test_api_jiu_nage_with_recommendations_asks_which(client):
    """推荐→就那个: does not order, asks which one."""
    sid = _sid()

    r1 = client.post("/api/chat", json={"session_id": sid, "message": "推荐"})
    assert r1.status_code == 200

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "就那个"})
    assert r2.status_code == 200
    s2 = r2.json()["state"]
    assert len(s2["current_order"]) == 0, "Must not order on 就那个"

    resp = r2.json()["response"]
    assert "第几个" in resp or "第一个" in resp or "菜名" in resp, (
        f"Response should ask for clarification: {resp}"
    )


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 7: Chinese number quantity (full API chain)
# ═══════════════════════════════════════════════════════════════════════

def test_api_chinese_number_quantity(client):
    """六个鸡腿饭 via API: quantity=6."""
    sid = _sid()

    r = client.post("/api/chat", json={"session_id": sid, "message": "六个鸡腿饭"})
    assert r.status_code == 200
    s = r.json()["state"]
    assert len(s["current_order"]) == 1
    assert s["current_order"][0]["name"] == "鸡腿饭"
    assert s["current_order"][0]["quantity"] == 6


def test_api_normal_append_via_api(client):
    """牛肉饭→鸡腿饭 via API: both items preserved."""
    sid = _sid()

    client.post("/api/chat", json={"session_id": sid, "message": "牛肉饭"})
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "鸡腿饭"})

    s = r2.json()["state"]
    assert len(s["current_order"]) == 2
    names = [item["name"] for item in s["current_order"]]
    assert "牛肉饭" in names
    assert "鸡腿饭" in names


def test_api_normal_clear_via_api(client):
    """牛肉饭→不要了→确认 via API: order cleared."""
    sid = _sid()

    client.post("/api/chat", json={"session_id": sid, "message": "牛肉饭"})
    client.post("/api/chat", json={"session_id": sid, "message": "不要了"})
    r3 = client.post("/api/chat", json={"session_id": sid, "message": "确认"})

    s = r3.json()["state"]
    assert len(s["current_order"]) == 0
    assert s["pending_action"] is None
    assert s["submitted"] is False


# ═══════════════════════════════════════════════════════════════════════
# API Scenario 8: Ambiguous candidate → select by ordinal
# ═══════════════════════════════════════════════════════════════════════

def test_api_ambiguous_then_ordinal_select(client):
    """牛肉那个→第二个: selects candidate[1] via API."""
    sid = _sid()

    r1 = client.post("/api/chat", json={"session_id": sid, "message": "牛肉那个"})
    assert r1.status_code == 200
    s1 = r1.json()["state"]
    assert s1["pending_action"] is not None
    assert s1["pending_action"]["type"] == "select_ambiguous_dish_candidate"

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "第二个"})
    assert r2.status_code == 200
    s2 = r2.json()["state"]
    assert len(s2["current_order"]) == 1
    assert s2["pending_action"] is None
    assert r2.json()["trace"]["fallbackUsed"] is False


def test_api_ambiguous_then_number_select(client):
    """牛肉那个→2: numeric index via API."""
    sid = _sid()

    client.post("/api/chat", json={"session_id": sid, "message": "牛肉那个"})
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "2"})
    assert r2.status_code == 200
    s2 = r2.json()["state"]
    assert len(s2["current_order"]) == 1
    assert s2["pending_action"] is None


def test_api_recommend_then_ambiguous_then_select(client):
    """推荐→牛肉那个→第二个: priority over recommendations via API."""
    sid = _sid()

    client.post("/api/chat", json={"session_id": sid, "message": "推荐"})
    client.post("/api/chat", json={"session_id": sid, "message": "牛肉那个"})
    r3 = client.post("/api/chat", json={"session_id": sid, "message": "第二个"})
    assert r3.status_code == 200
    s3 = r3.json()["state"]
    assert len(s3["current_order"]) == 1
    assert s3["pending_action"] is None
    assert r3.json()["trace"]["fallbackUsed"] is False


def test_api_ambiguous_cancel_clears_pending(client):
    """牛肉那个→算了: clears candidate pending via API."""
    sid = _sid()

    client.post("/api/chat", json={"session_id": sid, "message": "牛肉那个"})
    s1 = client.post("/api/chat", json={"session_id": sid, "message": "可乐"}).json()["state"]
    # Verify initial state — order should have 可乐 from a fresh test
    # Actually we need to set up correctly. Let me fix this — set up order first.
    pass  # See test below

    # Better approach: set up order with item first
    sid2 = _sid()
    client.post("/api/chat", json={"session_id": sid2, "message": "可乐"})
    client.post("/api/chat", json={"session_id": sid2, "message": "牛肉那个"})
    s = client.post("/api/chat", json={"session_id": sid2, "message": "牛肉那个"}).json()["state"]
    # pending should be set
    assert s["pending_action"] is not None

    r = client.post("/api/chat", json={"session_id": sid2, "message": "算了"})
    s_final = r.json()["state"]
    assert s_final["pending_action"] is None or s_final["pending_action"].get("type") != "select_ambiguous_dish_candidate"


def test_api_ambiguous_cancel_preserves_order(client):
    """牛肉那个 with existing order→算了: order preserved via API."""
    sid = _sid()

    # Order an item first
    client.post("/api/chat", json={"session_id": sid, "message": "可乐"})
    # Trigger ambiguous candidates
    client.post("/api/chat", json={"session_id": sid, "message": "牛肉那个"})
    # Cancel candidate selection
    r = client.post("/api/chat", json={"session_id": sid, "message": "算了"})

    s = r.json()["state"]
    # Order should still have 可乐
    assert len(s["current_order"]) >= 1
    names = [item["name"] for item in s["current_order"]]
    assert "可乐" in names, f"可乐 must remain after cancel, got {names}"
