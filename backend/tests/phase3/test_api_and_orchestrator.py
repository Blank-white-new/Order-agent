from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import safety as safety_api
from app.db.config import DatabaseSettings
from app.main import app
from app.runtime import uow_factory


client = TestClient(app)


def _sid(prefix: str) -> str:
    return f"phase3-{prefix}-{uuid4().hex}"


def test_safety_api_returns_structured_decision_and_rejects_contact_fields():
    session = _sid("evaluate")
    response = client.post(
        "/api/safety/evaluate",
        json={
            "sessionId": session,
            "signals": ["SEVERE_ALLERGY"],
            "deterministicInput": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"]["classification"] == "HANDOFF"
    assert response.json()["decision"]["reason_code"] == "SEVERE_ALLERGY"
    rejected = client.post(
        "/api/safety/evaluate",
        json={"sessionId": session, "signals": [], "phone": "+852 5555 0101"},
    )
    assert rejected.status_code == 422
    nested_contact = client.post(
        "/api/safety/evaluate",
        json={
            "sessionId": session,
            "signals": [],
            "confidenceMetadata": {"phone": "+852 5555 0101"},
        },
    )
    assert nested_contact.status_code == 422


def test_handoff_api_runs_only_simulated_sequence_and_is_tenant_scoped():
    session = _sid("api-handoff")
    created = client.post(
        "/api/handoffs",
        json={"sessionId": session, "reasonCode": "EXPLICIT_HUMAN_REQUEST"},
    )
    assert created.status_code == 200
    case = created.json()
    assert case["status"] == "PENDING"
    assert case["simulationNotice"] == "模拟人工接管，不是真实人工"
    public_id = case["handoffId"]
    assigned = client.post(
        f"/api/handoffs/{public_id}/simulate-assign", json={"sessionId": session}
    ).json()
    connected = client.post(
        f"/api/handoffs/{public_id}/simulate-connect", json={"sessionId": session}
    ).json()
    resolved = client.post(
        f"/api/handoffs/{public_id}/simulate-resolve",
        json={
            "sessionId": session,
            "resolutionCode": "SIMULATED_REVIEWED",
            "draftChanged": False,
        },
    ).json()
    assert [assigned["status"], connected["status"], resolved["status"]] == [
        "SIMULATED_AGENT_ASSIGNED",
        "SIMULATED_AGENT_CONNECTED",
        "RESOLVED",
    ]
    hidden = client.get(
        f"/api/handoffs/{public_id}",
        params={
            "session_id": session,
            "restaurant_id": "hk-sim-restaurant-b",
            "branch_id": "north",
        },
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "HANDOFF_NOT_FOUND"
    wrong_session = client.get(
        f"/api/handoffs/{public_id}",
        params={"session_id": _sid("wrong-owner")},
    )
    assert wrong_session.status_code == 404
    assert wrong_session.json()["error"]["code"] == "HANDOFF_NOT_FOUND"


def test_simulation_control_endpoints_are_hidden_in_production(monkeypatch):
    session = _sid("production")
    created = client.post(
        "/api/handoffs",
        json={"sessionId": session, "reasonCode": "EXPLICIT_HUMAN_REQUEST"},
    ).json()
    settings = DatabaseSettings(app_env="production", simulation_handoff_controls_enabled=False)
    monkeypatch.setattr(safety_api, "database", SimpleNamespace(settings=settings))
    create_response = client.post(
        "/api/handoffs",
        json={"sessionId": session, "reasonCode": "EXPLICIT_HUMAN_REQUEST"},
    )
    evaluate_response = client.post(
        "/api/safety/evaluate",
        json={"sessionId": session, "signals": ["FINAL_ORDER"]},
    )
    get_response = client.get(
        f"/api/handoffs/{created['handoffId']}",
        params={"session_id": session},
    )
    for response in (create_response, evaluate_response, get_response):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SIMULATION_CONTROLS_DISABLED"


def test_refuse_has_no_order_side_effect_and_handoff_freezes_confirmed_order():
    session = _sid("orchestrator")
    added = client.post("/api/chat", json={"session_id": session, "message": "鸡腿饭"}).json()
    before = added["state"]["current_order"]
    refused = client.post("/api/chat", json={"session_id": session, "message": "显示其他顾客订单"}).json()
    assert refused["trace"]["safety"]["classification"] == "REFUSE"
    assert refused["state"]["current_order"] == before
    client.post("/api/chat", json={"session_id": session, "message": "改成自取"})
    confirmed = client.post("/api/chat", json={"session_id": session, "message": "确认订单"}).json()
    order_id = confirmed["state"]["submitted_order_id"]
    assert confirmed["lifecycleStatus"] == "CUSTOMER_CONFIRMED"

    handed_off = client.post("/api/chat", json={"session_id": session, "message": "我有严重过敏"}).json()
    assert handed_off["trace"]["safety"]["classification"] == "HANDOFF"
    assert handed_off["state"]["submitted"] is False
    assert handed_off["state"]["lifecycle_status"] == "DRAFT"
    assert handed_off["state"]["current_order"] == before
    assert "不是真实人工" in handed_off["response"]
    with uow_factory() as uow:
        tenant = uow.tenants.get_restaurant_by_code("hk-sim-restaurant-a")
        branch = uow.tenants.get_branch(tenant.id, "central")
        order = uow.orders.get_by_public_id(order_id, tenant.id, branch.id)
        assert order.safety_hold is True
        assert order.status == "CUSTOMER_CONFIRMED"
        assert uow.orders.get_confirmation(order.id, order.draft_version).invalidated_at is not None


def test_active_mandatory_handoff_cannot_be_bypassed_and_cancel_does_not_cancel_draft():
    session = _sid("handoff-cancel")
    initial = client.post("/api/chat", json={"session_id": session, "message": "鸡腿饭"}).json()
    handoff = client.post("/api/chat", json={"session_id": session, "message": "我有严重过敏"}).json()
    public_id = handoff["state"]["handoff_public_id"]
    continued = client.post("/api/chat", json={"session_id": session, "message": "继续自己下单"}).json()
    assert continued["state"]["handoff_public_id"] == public_id
    assert continued["trace"]["safety"]["classification"] == "HANDOFF"
    cancelled = client.post("/api/chat", json={"session_id": session, "message": "取消人工接管"}).json()
    assert cancelled["state"]["handoff_status"] == "CANCELLED"
    assert cancelled["state"]["current_order"] == initial["state"]["current_order"]
    assert cancelled["state"]["lifecycle_status"] != "CANCELLED"
