from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Customer, OrderEvent, Restaurant
from app.domain.errors import DomainError
from app.main import app
from app.services.customer_service import CustomerService
from .helpers import persisted_state


def test_simulation_only_rejects_non_synthetic_customer(phase2):
    tenant = phase2.tenant_service.resolve()
    service = CustomerService(phase2.uow_factory, simulation_data_only=True)
    with pytest.raises(DomainError) as error:
        service.create(
            restaurant_id=tenant.restaurant_id,
            external_reference="not-synthetic",
            display_name="not stored",
            is_synthetic=False,
        )
    assert error.value.code == "SIMULATION_DATA_REQUIRED"
    with phase2.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0


def test_seed_names_and_metadata_are_explicitly_synthetic(phase2):
    with phase2.database.session_factory() as session:
        restaurants = list(session.scalars(select(Restaurant)))
        assert all(restaurant.is_simulation for restaurant in restaurants)
        assert all("Synthetic" in restaurant.name for restaurant in restaurants)
        assert session.scalar(select(func.count()).select_from(Customer)) == 0


def test_order_events_exclude_contact_address_and_transcript(phase2):
    state = persisted_state(phase2, "redacted-events")
    state.phone = "synthetic-phone-value"
    state.official_delivery_address = "synthetic-address-value"
    phase2.session_store.set("redacted-events", state)
    result = phase2.order_service.confirm_order(session_key="redacted-events", state=state)
    with phase2.database.session_factory() as session:
        payloads = [str(payload) for payload in session.scalars(select(OrderEvent.payload_json))]
    serialized = " ".join(payloads)
    assert "synthetic-phone-value" not in serialized
    assert "synthetic-address-value" not in serialized
    assert result.merchant_status == "NOT_INTEGRATED"


def test_api_optional_tenant_fields_bind_session_and_reject_switch():
    client = TestClient(app)
    session_id = "tenant-api-" + uuid.uuid4().hex
    first = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "有啥",
            "restaurantId": "hk-sim-restaurant-a",
            "branchId": "central",
        },
    )
    assert first.status_code == 200
    mismatch = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "有啥",
            "restaurantId": "hk-sim-restaurant-b",
            "branchId": "north",
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json() == {
        "error": {
            "code": "TENANT_CONTEXT_MISMATCH",
            "message": "The session is bound to a different tenant context.",
        }
    }


def test_menu_api_accepts_tenant_headers_and_returns_minor_units():
    client = TestClient(app)
    response = client.get(
        "/api/menu",
        headers={"X-Restaurant-Id": "hk-sim-restaurant-b", "X-Branch-Id": "north"},
    )
    assert response.status_code == 200
    chicken = next(item for item in response.json()["items"] if item["id"] == "chicken_leg_rice")
    assert chicken["base_price_minor"] == 2800
    assert chicken["currency"] == "HKD"


def test_database_safe_label_never_contains_url_or_credentials(phase2):
    expected_label = "sqlite" if phase2.settings.is_sqlite else "postgresql+psycopg"
    assert phase2.settings.safe_database_label == expected_label
    assert phase2.settings.database_url not in phase2.settings.safe_database_label
    assert "://" not in phase2.settings.safe_database_label
