from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.chat import _safe_trace
from app.main import app


def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def ensure_phase4_catalog_is_published(phase4):
    """Publish Phase 4 after earlier PostgreSQL suites rebuild their shared DB."""
    return phase4


def test_chat_backward_compatibility_and_locale_metadata():
    response = client().post(
        "/api/chat",
        json={"session_id": f"p4-api-{uuid.uuid4().hex}", "message": "菜单"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["responseLocale"] == "zh-CN"
    assert body["detectedLocale"] == "zh-CN"
    assert isinstance(body["localeConfidence"], float)
    assert body["mixedLanguage"] is False
    assert "safetyClassification" in body
    assert "handoffStatus" in body


def test_chat_accepts_camel_case_locale_fields_and_returns_cantonese():
    response = client().post(
        "/api/chat",
        json={
            "session_id": f"p4-api-yue-{uuid.uuid4().hex}",
            "message": "我要兩份雞髀飯",
            "restaurantId": "hk-sim-restaurant-a",
            "branchId": "central",
            "localeHint": "yue-Hant-HK",
            "localeLocked": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["detectedLocale"] == "yue-Hant-HK"
    assert body["responseLocale"] == "yue-Hant-HK"
    assert body["trace"]["multilingual"]["canonicalIntent"] == "ADD_ITEM"
    assert body["trace"]["multilingual"]["entities"]["item_code"] == "chicken_leg_rice"


def test_mixed_input_is_reported_without_forcing_single_input_locale():
    response = client().post(
        "/api/chat",
        json={
            "session_id": f"p4-api-mix-{uuid.uuid4().hex}",
            "message": "我要 two portions chicken leg rice 少辣 please",
            "restaurantId": "hk-sim-restaurant-a",
            "branchId": "central",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["detectedLocale"] == "mixed"
    assert body["mixedLanguage"] is True
    assert body["responseLocale"] in {"zh-CN", "en-HK"}


def test_invalid_locale_has_stable_error_and_menu_is_strict():
    chat = client().post(
        "/api/chat",
        json={"session_id": f"p4-api-bad-{uuid.uuid4().hex}", "message": "menu", "locale": "fr-FR"},
    )
    menu = client().get("/api/menu?locale=fr-FR")
    assert chat.status_code == 422
    assert menu.status_code == 422
    assert chat.json()["error"]["code"] == "INVALID_LOCALE"
    assert menu.json()["error"]["code"] == "INVALID_LOCALE"


def test_development_trace_redacts_contact_fields():
    response = client().post(
        "/api/chat",
        json={
            "session_id": f"p4-api-contact-{uuid.uuid4().hex}",
            "message": "the phone number is 55550101",
            "locale": "en-HK",
        },
    )
    body = response.json()
    trace_text = str(body["trace"])
    assert "55550101" not in trace_text
    assert "[redacted]" in trace_text


def test_production_trace_whitelist_excludes_parser_and_raw_text():
    safe = _safe_trace(
        {
            "finalIntent": "order_food",
            "selectedAgent": "OrderAgent",
            "multilingual": {"entities": {"phone": "55550101"}},
            "userMessage": "private",
            "normalizedMessage": "private",
            "safety": {"classification": "AUTO_DRAFT"},
        },
        production=True,
    )
    assert safe == {
        "finalIntent": "order_food",
        "selectedAgent": "OrderAgent",
        "safety": {"classification": "AUTO_DRAFT"},
    }


def test_menu_names_are_localized_but_item_identity_is_stable():
    http = client()
    zh = http.get("/api/menu?restaurantId=hk-sim-restaurant-a&branchId=central&locale=zh-CN").json()
    yue = http.get("/api/menu?restaurantId=hk-sim-restaurant-a&branchId=central&locale=yue-Hant-HK").json()
    en = http.get("/api/menu?restaurantId=hk-sim-restaurant-a&branchId=central&locale=en-HK").json()
    def indexed(payload):
        return {item["id"]: item for item in payload["items"]}
    by_locale = [indexed(value) for value in (zh, yue, en)]
    assert all("chicken_leg_rice" in values for values in by_locale)
    assert len({values["chicken_leg_rice"]["name"] for values in by_locale}) == 3
