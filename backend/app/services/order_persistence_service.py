from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.models import (
    IdempotencyRecord,
    Order,
    OrderConfirmation,
    OrderEvent,
    OrderItem as OrderItemModel,
)
from app.domain.enums import ActorType, MerchantStatus, OrderStatus
from app.domain.errors import (
    DomainError,
    confirmation_stale,
    database_write_failed,
    idempotency_conflict,
    item_unavailable,
    session_version_conflict,
    simulation_data_required,
    tenant_context_mismatch,
)
from app.services.order_lifecycle_service import OrderLifecycleService
from app.services.modifier_validation_service import ModifierSelectionValidator
from app.services.tenant_service import TenantService
from app.state.session_state import SessionState
from app.state.session_persistence import apply_contact, contact_from_state, state_json_without_contact


@dataclass(frozen=True)
class ConfirmationResult:
    public_id: str
    lifecycle_status: str
    merchant_status: str
    subtotal_minor: int
    delivery_fee_minor: int
    total_minor: int
    currency: str
    idempotent_replay: bool
    persistence_version: int


class OrderPersistenceService:
    def __init__(self, uow_factory, tenant_service: TenantService, *, simulation_data_only: bool = True) -> None:
        self.uow_factory = uow_factory
        self.tenant_service = tenant_service
        self.simulation_data_only = simulation_data_only
        self.lifecycle = OrderLifecycleService()
        self.modifier_validator = ModifierSelectionValidator()

    def confirm_order(
        self,
        *,
        session_key: str,
        state: SessionState,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
        idempotency_key: str | None = None,
        delivery_zone_code: str | None = None,
        source: str = "CHAT_EXPLICIT_CONFIRMATION",
    ) -> ConfirmationResult:
        original_state = state.clone()
        tenant = self.tenant_service.resolve(restaurant_code or state.restaurant_code, branch_code or state.branch_code)
        if self.simulation_data_only and (not tenant.is_simulation or not state.is_synthetic):
            raise simulation_data_required()
        request = self._authoritative_request(tenant, state, delivery_zone_code)
        fingerprint = _fingerprint(request)
        key = idempotency_key or f"confirm:{session_key}:{state.draft_version}"
        try:
            return self._confirm_transaction(tenant, session_key, state, key, fingerprint, request, source)
        except IntegrityError:
            self._restore_state(state, original_state)
            return self._resolve_concurrent_replay(tenant, state, key, fingerprint)
        except DomainError:
            self._restore_state(state, original_state)
            raise
        except SQLAlchemyError as exc:
            self._restore_state(state, original_state)
            raise database_write_failed() from exc

    def _authoritative_request(self, tenant, state: SessionState, delivery_zone_code: str | None) -> dict:
        with self.uow_factory() as uow:
            items = []
            currencies = set()
            for entry in state.current_order:
                menu_item = uow.menus.get_item_by_code(tenant.branch_id, entry.item_id)
                if not menu_item or not menu_item.active:
                    raise item_unavailable()
                if not menu_item.available:
                    raise item_unavailable(sold_out=True)
                currencies.add(menu_item.currency)
                allergen_snapshot = menu_item.allergens or [
                    {
                        "code": None,
                        "name": None,
                        "declaration": "UNKNOWN",
                        "source": "missing-authoritative-declaration",
                        "verifiedAt": None,
                    }
                ]
                modifier_snapshot = self.modifier_validator.validate(uow.menus, menu_item.id, entry.options)
                if entry.spicy_level:
                    modifier_snapshot.append({"type": "spicy-level", "name": entry.spicy_level, "priceDeltaMinor": 0})
                if entry.exclusions:
                    modifier_snapshot.append({"type": "exclusions", "values": list(entry.exclusions), "priceDeltaMinor": 0})
                if entry.notes:
                    modifier_snapshot.append({"type": "synthetic-note", "present": True, "priceDeltaMinor": 0})
                items.append(
                    {
                        "menu_item_id": menu_item.id,
                        "menu_version_id": menu_item.menu_version_id,
                        "code": menu_item.code,
                        "name": menu_item.name,
                        "unit_price_minor": menu_item.base_price_minor
                        + sum(modifier["priceDeltaMinor"] for modifier in modifier_snapshot),
                        "quantity": entry.quantity,
                        "modifier_snapshot": modifier_snapshot,
                        "allergen_snapshot": allergen_snapshot,
                    }
                )
            if not items:
                raise DomainError("EMPTY_ORDER", "An empty order cannot be confirmed.", 422)
            if len(currencies) != 1 or tenant.currency not in currencies:
                raise DomainError("CURRENCY_MISMATCH", "Items from different currencies cannot be mixed.")
            zone = None
            delivery_fee_minor = 0
            if state.fulfillment_type == "delivery":
                zone = uow.operations.get_zone(tenant.branch_id, delivery_zone_code)
                if not zone:
                    raise DomainError("DELIVERY_ZONE_NOT_FOUND", "No synthetic delivery zone is available.", 422)
                delivery_fee_minor = zone.fee_minor
            subtotal_minor = sum(item["unit_price_minor"] * item["quantity"] for item in items)
            return {
                "restaurant_id": tenant.restaurant_id,
                "branch_id": tenant.branch_id,
                "draft_version": state.draft_version,
                "currency": tenant.currency,
                "fulfillment_type": state.fulfillment_type,
                "delivery_zone_id": zone.id if zone else None,
                "delivery_fee_minor": delivery_fee_minor,
                "subtotal_minor": subtotal_minor,
                "total_minor": subtotal_minor + delivery_fee_minor,
                "items": items,
            }

    def _confirm_transaction(self, tenant, session_key, state, key, fingerprint, request, source) -> ConfirmationResult:
        with self.uow_factory() as uow:
            session_row = uow.sessions.get_by_session_key(session_key)
            if not session_row or session_row.restaurant_id != tenant.restaurant_id or session_row.branch_id != tenant.branch_id:
                raise tenant_context_mismatch()
            persisted_state = SessionState(**dict(session_row.state_json or {}))
            apply_contact(persisted_state, uow.sessions.get_contact(session_row.id))
            if _draft_fingerprint(persisted_state) != _draft_fingerprint(state):
                raise confirmation_stale()
            existing = uow.idempotency.get(tenant.restaurant_id, tenant.branch_id, "ORDER_CONFIRMATION", key)
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise idempotency_conflict()
                order = uow.orders.get_by_public_id(existing.resource_id, tenant.restaurant_id, tenant.branch_id)
                if not order:
                    raise database_write_failed()
                confirmation = uow.orders.get_confirmation(order.id, state.draft_version)
                if order.status != OrderStatus.CUSTOMER_CONFIRMED.value or not confirmation or confirmation.invalidated_at:
                    raise confirmation_stale()
                self._apply_confirmed_state(state, order.public_id, session_row.version)
                return self._result(order, replay=True, persistence_version=session_row.version)
            if state.persistence_version not in {0, session_row.version}:
                raise session_version_conflict()

            public_id = "SIM-" + uuid.uuid4().hex[:16].upper()
            order = Order(
                public_id=public_id,
                restaurant_id=tenant.restaurant_id,
                branch_id=tenant.branch_id,
                session_id=session_row.id,
                customer_id=None,
                status=OrderStatus.DRAFT.value,
                draft_version=state.draft_version,
                currency=request["currency"],
                subtotal_minor=request["subtotal_minor"],
                delivery_fee_minor=request["delivery_fee_minor"],
                total_minor=request["total_minor"],
                fulfillment_type=request["fulfillment_type"],
                delivery_zone_id=request["delivery_zone_id"],
                is_synthetic=True,
            )
            uow.orders.add(order)
            uow.flush()
            uow.orders.add(
                OrderEvent(
                    order_id=order.id,
                    sequence_number=1,
                    event_type="ORDER_DRAFT_CREATED",
                    payload_json={"draftVersion": state.draft_version, "synthetic": True},
                    actor_type=ActorType.SYSTEM.value,
                )
            )
            for item in request["items"]:
                uow.orders.add(
                    OrderItemModel(
                        order_id=order.id,
                        restaurant_id=tenant.restaurant_id,
                        menu_item_id=item["menu_item_id"],
                        menu_version_id=item["menu_version_id"],
                        item_code_snapshot=item["code"],
                        item_name_snapshot=item["name"],
                        unit_price_minor=item["unit_price_minor"],
                        quantity=item["quantity"],
                        modifier_snapshot_json=item["modifier_snapshot"],
                        allergen_snapshot_json=item["allergen_snapshot"],
                        line_total_minor=item["unit_price_minor"] * item["quantity"],
                    )
                )
            confirmation_fingerprint = _fingerprint({"order": public_id, "draftVersion": state.draft_version, "request": fingerprint})
            uow.orders.add(
                OrderConfirmation(
                    order_id=order.id,
                    draft_version=state.draft_version,
                    confirmation_fingerprint=confirmation_fingerprint,
                    source=source,
                )
            )
            self.lifecycle.transition(
                uow,
                order,
                OrderStatus.CUSTOMER_CONFIRMED,
                actor_type=ActorType.CUSTOMER,
                payload={"draftVersion": state.draft_version, "source": source},
            )
            uow.idempotency.add(
                IdempotencyRecord(
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                    scope="ORDER_CONFIRMATION",
                    idempotency_key=key,
                    request_fingerprint=fingerprint,
                    resource_type="ORDER",
                    resource_id=public_id,
                    status="SUCCEEDED",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                )
            )
            expected_version = session_row.version
            self._apply_confirmed_state(state, public_id, expected_version + 1)
            uow.sessions.save_contact(session_row.id, **contact_from_state(state))
            if not uow.sessions.save_optimistic(
                session_row,
                expected_version,
                state_json_without_contact(state, persistence_version=expected_version + 1),
            ):
                raise session_version_conflict()
            uow.flush()
            return self._result(order, replay=False, persistence_version=expected_version + 1)

    def _resolve_concurrent_replay(self, tenant, state: SessionState, key: str, fingerprint: str) -> ConfirmationResult:
        with self.uow_factory() as uow:
            existing = uow.idempotency.get(tenant.restaurant_id, tenant.branch_id, "ORDER_CONFIRMATION", key)
            if not existing:
                raise database_write_failed()
            if existing.request_fingerprint != fingerprint:
                raise idempotency_conflict()
            order = uow.orders.get_by_public_id(existing.resource_id, tenant.restaurant_id, tenant.branch_id)
            if not order:
                raise database_write_failed()
            confirmation = uow.orders.get_confirmation(order.id, state.draft_version)
            if order.status != OrderStatus.CUSTOMER_CONFIRMED.value or not confirmation or confirmation.invalidated_at:
                raise confirmation_stale()
            self._apply_confirmed_state(state, order.public_id, state.persistence_version)
            return self._result(order, replay=True, persistence_version=state.persistence_version)

    def invalidate_confirmation(self, public_id: str, restaurant_code: str, branch_code: str) -> int:
        tenant = self.tenant_service.resolve(restaurant_code, branch_code)
        with self.uow_factory() as uow:
            order = uow.orders.get_by_public_id(public_id, tenant.restaurant_id, tenant.branch_id)
            if not order:
                raise DomainError("ORDER_NOT_FOUND", "Order was not found.", 404)
            confirmation = uow.orders.get_confirmation(order.id, order.draft_version)
            if not confirmation or confirmation.invalidated_at:
                raise confirmation_stale()
            confirmation.invalidated_at = datetime.now(timezone.utc)
            order.draft_version += 1
            self.lifecycle.transition(
                uow,
                order,
                OrderStatus.CANCELLED,
                actor_type=ActorType.SYSTEM,
                payload={"reason": "CONFIRMATION_INVALIDATED", "newDraftVersion": order.draft_version},
            )
            return order.draft_version

    def _apply_confirmed_state(self, state: SessionState, public_id: str, persistence_version: int) -> None:
        state.submitted = True  # deprecated compatibility lock, not merchant acceptance
        state.submitted_order_id = public_id
        state.stage = "submitted"
        state.lifecycle_status = OrderStatus.CUSTOMER_CONFIRMED.value
        state.merchant_status = MerchantStatus.NOT_INTEGRATED.value
        state.confirmation_valid = True
        state.persistence_version = persistence_version

    def _result(self, order: Order, *, replay: bool, persistence_version: int) -> ConfirmationResult:
        return ConfirmationResult(
            public_id=order.public_id,
            lifecycle_status=order.status,
            merchant_status=MerchantStatus.NOT_INTEGRATED.value,
            subtotal_minor=order.subtotal_minor,
            delivery_fee_minor=order.delivery_fee_minor,
            total_minor=order.total_minor,
            currency=order.currency,
            idempotent_replay=replay,
            persistence_version=persistence_version,
        )

    def _restore_state(self, state: SessionState, snapshot: SessionState) -> None:
        for field_name in SessionState.model_fields:
            setattr(state, field_name, deepcopy(getattr(snapshot, field_name)))


def _fingerprint(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _draft_fingerprint(state: SessionState) -> str:
    return _fingerprint(
        {
            "restaurant": state.restaurant_code,
            "branch": state.branch_code,
            "draftVersion": state.draft_version,
            "fulfillmentType": state.fulfillment_type,
            "deliveryAddress": state.official_delivery_address,
            "phonePresent": bool(state.phone),
            "items": [
                {
                    "itemId": item.item_id,
                    "quantity": item.quantity,
                    "options": sorted(item.options),
                    "spicyLevel": item.spicy_level,
                    "exclusions": sorted(item.exclusions),
                    "notes": item.notes,
                }
                for item in state.current_order
            ],
        }
    )
