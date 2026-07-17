from __future__ import annotations

from typing import Any

from app.state.session_state import SessionState


class HandoffSummaryService:
    VERSION = 1

    def build(self, *, case, tenant, state: SessionState, order=None, order_items=()) -> dict[str, Any]:
        if order is not None:
            items = [
                {
                    "itemCode": item.item_code_snapshot,
                    "itemName": item.item_name_snapshot,
                    "quantity": item.quantity,
                    "unitPriceMinor": item.unit_price_minor,
                    "lineTotalMinor": item.line_total_minor,
                    "modifiers": item.modifier_snapshot_json,
                }
                for item in order_items
            ]
            subtotal_minor = order.subtotal_minor
            delivery_fee_minor = order.delivery_fee_minor
            total_minor = order.total_minor
            currency = order.currency
            lifecycle = order.status
        else:
            items = []
            subtotal_minor = 0
            for item in state.current_order:
                unit_minor = item.unit_price_minor if item.unit_price_minor is not None else item.price * 100
                line_total = unit_minor * item.quantity
                subtotal_minor += line_total
                items.append(
                    {
                        "itemCode": item.item_id,
                        "itemName": item.name,
                        "quantity": item.quantity,
                        "unitPriceMinor": unit_minor,
                        "lineTotalMinor": line_total,
                        "modifiers": list(item.options),
                    }
                )
            delivery_fee_minor = 0
            total_minor = subtotal_minor
            currency = items and state.current_order[0].currency or tenant.currency
            lifecycle = state.lifecycle_status

        confirmed: list[str] = []
        if state.confirmation_valid:
            confirmed.append("final_order")
        if state.official_delivery_address:
            confirmed.append("address")
        if state.phone:
            confirmed.append("phone")
        candidates = ("final_order", "address", "phone", "delivery_fee")
        unconfirmed = [field for field in candidates if field not in confirmed]
        return {
            "handoffId": case.public_id,
            "restaurantCode": tenant.restaurant_code,
            "branchCode": tenant.branch_code,
            "locale": "zh-CN",
            "summaryVersion": self.VERSION,
            "order": {
                "items": items,
                "subtotalMinor": subtotal_minor,
                "deliveryFeeMinor": delivery_fee_minor,
                "totalMinor": total_minor,
                "currency": currency,
                "lifecycleStatus": lifecycle,
            },
            "confirmedFields": sorted(confirmed),
            "unconfirmedFields": sorted(unconfirmed),
            "contact": {
                "phoneMasked": "***" if state.phone else None,
                "addressMasked": "***" if state.official_delivery_address else None,
            },
            "handoffReasonCode": case.reason_code,
            "riskIds": sorted(case.risk_ids_json),
            "blockedActions": sorted(case.blocked_actions_json),
            "safeContext": ["SYNTHETIC_SIMULATION_ONLY", f"REASON:{case.reason_code}"],
            "forbiddenActions": sorted(
                set(case.blocked_actions_json)
                | {"CLAIM_REAL_HUMAN_CONNECTED", "GUARANTEE_ALLERGEN_SAFE"}
            ),
            "isSynthetic": True,
        }
