from __future__ import annotations

from pathlib import Path

from sqlalchemy import Integer, inspect

from app.db.models import (
    Base,
    DeliveryZone,
    MenuItem,
    ModifierOption,
    Order,
    OrderItem,
)
from app.domain.enums import AllergenDeclaration, OrderStatus
from app.domain.errors import (
    branch_not_found,
    confirmation_stale,
    database_write_failed,
    idempotency_conflict,
    invalid_order_transition,
    item_unavailable,
    menu_publish_conflict,
    modifier_ambiguous,
    modifier_duplicate,
    modifier_not_available,
    modifier_required,
    modifier_too_few,
    modifier_too_many,
    no_published_menu,
    restaurant_not_found,
    simulation_data_required,
    tenant_context_mismatch,
)


def test_all_money_columns_are_integer_minor_units():
    for model, columns in [
        (MenuItem, ["base_price_minor"]),
        (ModifierOption, ["price_delta_minor"]),
        (DeliveryZone, ["fee_minor", "minimum_order_minor"]),
        (Order, ["subtotal_minor", "delivery_fee_minor", "total_minor"]),
        (OrderItem, ["unit_price_minor", "line_total_minor"]),
    ]:
        table = inspect(model).local_table
        assert all(isinstance(table.c[column].type, Integer) for column in columns)


def test_allergen_declarations_never_define_unverified_free_from():
    assert {value.value for value in AllergenDeclaration} == {"CONTAINS", "MAY_CONTAIN", "UNKNOWN"}
    assert "FREE_FROM" not in Base.metadata.tables["menu_item_allergens"].c.declaration.type.__str__()


def test_order_lifecycle_has_exact_phase2_states():
    assert {status.value for status in OrderStatus} == {
        "DRAFT",
        "CUSTOMER_CONFIRMED",
        "SUBMISSION_STARTED",
        "MERCHANT_PENDING",
        "MERCHANT_ACCEPTED",
        "MERCHANT_REJECTED",
        "SUBMISSION_FAILED",
        "CANCELLED",
        "COMPLETED",
    }


def test_stable_domain_error_codes_and_http_semantics():
    errors = [
        tenant_context_mismatch(),
        restaurant_not_found(),
        branch_not_found(),
        no_published_menu(),
        item_unavailable(),
        item_unavailable(sold_out=True),
        invalid_order_transition("DRAFT", "MERCHANT_ACCEPTED"),
        confirmation_stale(),
        idempotency_conflict(),
        simulation_data_required(),
        database_write_failed(),
        menu_publish_conflict(),
        modifier_required("size"),
        modifier_too_few("size"),
        modifier_too_many("size"),
        modifier_not_available(),
        modifier_ambiguous(),
        modifier_duplicate(),
    ]
    assert {error.code for error in errors} >= {
        "TENANT_CONTEXT_MISMATCH",
        "RESTAURANT_NOT_FOUND",
        "BRANCH_NOT_FOUND",
        "NO_PUBLISHED_MENU",
        "ITEM_UNAVAILABLE",
        "ITEM_SOLD_OUT",
        "INVALID_ORDER_TRANSITION",
        "CONFIRMATION_STALE",
        "IDEMPOTENCY_CONFLICT",
        "SIMULATION_DATA_REQUIRED",
        "DATABASE_WRITE_FAILED",
        "MENU_PUBLISH_CONFLICT",
        "MODIFIER_REQUIRED",
        "MODIFIER_TOO_FEW",
        "MODIFIER_TOO_MANY",
        "MODIFIER_NOT_AVAILABLE",
        "MODIFIER_AMBIGUOUS",
        "MODIFIER_DUPLICATE",
    }
    assert restaurant_not_found().http_status == 404
    assert branch_not_found().http_status == 404
    assert idempotency_conflict().http_status == 409
    assert simulation_data_required().http_status == 422


def test_agents_api_and_business_services_do_not_issue_sql_directly():
    app_root = Path(__file__).resolve().parents[2] / "app"
    forbidden_imports = ("from sqlalchemy import select", "from sqlalchemy import update", "from sqlalchemy import text")
    for folder in ["agents", "api", "services"]:
        for path in (app_root / folder).glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(token in source for token in forbidden_imports), path
