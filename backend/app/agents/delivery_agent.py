from __future__ import annotations

from app.models.schemas import Interpretation
from app.services.delivery_service import DeliveryService
from app.state.session_state import DeliveryAddressCandidate, SessionState


class DeliveryAgent:
    name = "DeliveryAgent"

    def __init__(self, delivery_service: DeliveryService) -> None:
        self.delivery_service = delivery_service

    def handle(self, interpretation: Interpretation, state: SessionState, handler: str | None = None) -> dict:
        handler = handler or interpretation.intent
        if handler == "confirm_pending_address":
            return self._confirm_pending_address(state)
        if handler == "reject_pending_address":
            return self._reject_pending_address()
        if handler == "provide_fulfillment_slot":
            return self._provide_fulfillment(interpretation)
        if handler == "address_candidate":
            return self._address_candidate(interpretation, state)
        if handler == "provide_delivery_address":
            return self._provide_address(interpretation)
        if handler == "provide_phone":
            return self._provide_phone(interpretation)
        if interpretation.intent == "ask_delivery_fee":
            return self._ask_fee(interpretation)
        if interpretation.intent == "ask_deliverability":
            return self._ask_deliverability(interpretation)
        return self._ask_eta(interpretation)

    def _provide_fulfillment(self, interpretation: Interpretation) -> dict:
        fulfillment_type = interpretation.entities.get("fulfillment_type", "delivery")
        if fulfillment_type == "pickup":
            return {
                "agent": self.name,
                "handler": "provide_fulfillment_slot",
                "message": "好的，改为自取。确认订单后就可以提交。",
                "patch": {"fulfillment_type": "pickup", "stage": "confirming", "official_delivery_address": None},
            }
        return {
            "agent": self.name,
            "handler": "provide_fulfillment_slot",
            "message": "好的，选择配送。请发一下配送地址。",
            "patch": {"fulfillment_type": "delivery", "stage": "collecting_address"},
        }

    def _address_candidate(self, interpretation: Interpretation, state: SessionState) -> dict:
        if state.pending_delivery_address_candidate or state.stage == "collecting_address":
            return self._provide_address(interpretation)
        address = self.delivery_service.normalize_address(interpretation.entities.get("address"))
        if not address:
            return {
                "agent": self.name,
                "handler": "address_candidate",
                "message": "这个地址我没识别清楚，可以再发一次吗？",
                "patch": {},
            }
        candidate = DeliveryAddressCandidate(
            raw=interpretation.entities.get("address", address),
            normalized=address,
            source="plain_address",
            confidence=0.85,
            requires_confirmation=True,
        )
        return {
            "agent": self.name,
            "handler": "address_candidate",
            "message": f"要用{address}作为配送地址吗？",
            "patch": {"pending_delivery_address_candidate": candidate, "last_address_mention": address},
        }

    def _ask_eta(self, interpretation: Interpretation) -> dict:
        address = self.delivery_service.normalize_address(interpretation.entities.get("address"))
        if not address:
            return {
                "agent": self.name,
                "handler": "ask_delivery_eta",
                "message": "可以先告诉我配送地址，我再帮你估算送达时间。",
                "patch": {"stage": "collecting_address"},
            }
        eta = self.delivery_service.estimate_eta(address)
        candidate = DeliveryAddressCandidate(
            raw=interpretation.entities.get("address", address),
            normalized=address,
            source="eta_question",
            confidence=0.95,
            requires_confirmation=True,
        )
        return {
            "agent": self.name,
            "handler": "ask_delivery_eta",
            "message": f"送到{address}大约{eta}分钟。要用这个地址吗？",
            "patch": {"pending_delivery_address_candidate": candidate},
        }

    def _ask_fee(self, interpretation: Interpretation) -> dict:
        address = self.delivery_service.normalize_address(interpretation.entities.get("address"))
        if not address:
            return {
                "agent": self.name,
                "handler": "ask_delivery_fee",
                "message": "告诉我配送地址后，我可以帮你算配送费。",
                "patch": {"stage": "collecting_address"},
            }
        fee = self.delivery_service.estimate_fee(address)
        candidate = DeliveryAddressCandidate(
            raw=interpretation.entities.get("address", address),
            normalized=address,
            source="fee_question",
            confidence=0.95,
            requires_confirmation=True,
        )
        return {
            "agent": self.name,
            "handler": "ask_delivery_fee",
            "message": f"到{address}配送费{fee}元。要用这个地址吗？",
            "patch": {"pending_delivery_address_candidate": candidate},
        }

    def _ask_deliverability(self, interpretation: Interpretation) -> dict:
        address = self.delivery_service.normalize_address(interpretation.entities.get("address"))
        if not address:
            return {
                "agent": self.name,
                "handler": "ask_deliverability",
                "message": "把具体地址发我，我帮你确认能不能送到。",
                "patch": {"stage": "collecting_address"},
            }
        can_deliver = self.delivery_service.can_deliver(address)
        candidate = DeliveryAddressCandidate(
            raw=interpretation.entities.get("address", address),
            normalized=address,
            source="deliverability_question",
            confidence=0.95,
            requires_confirmation=True,
        )
        message = f"{address}可以送。要用这个地址吗？" if can_deliver else f"{address}暂时送不到。"
        return {
            "agent": self.name,
            "handler": "ask_deliverability",
            "message": message,
            "patch": {"pending_delivery_address_candidate": candidate},
        }

    def _provide_address(self, interpretation: Interpretation) -> dict:
        address = self.delivery_service.normalize_address(interpretation.entities.get("address"))
        if not address:
            return {
                "agent": self.name,
                "handler": "provide_delivery_address",
                "message": "这个地址我没识别清楚，可以再发一次吗？",
                "patch": {},
            }
        return {
            "agent": self.name,
            "handler": "provide_delivery_address",
            "message": f"配送地址记为{address}。请发一下联系电话。",
            "patch": {
                "official_delivery_address": address,
                "pending_delivery_address_candidate": None,
                "stage": "collecting_phone",
            },
        }

    def _provide_phone(self, interpretation: Interpretation) -> dict:
        phone = interpretation.entities.get("phone")
        return {
            "agent": self.name,
            "handler": "provide_phone",
            "message": "电话已记下。确认订单后就可以提交。",
            "patch": {"phone": phone, "stage": "confirming"},
        }

    def _confirm_pending_address(self, state: SessionState) -> dict:
        candidate = state.pending_delivery_address_candidate
        if not candidate:
            return {
                "agent": self.name,
                "handler": "confirm_pending_address",
                "message": "现在没有待确认地址。",
                "patch": {},
            }
        return {
            "agent": self.name,
            "handler": "confirm_pending_address",
            "message": f"好，配送地址用{candidate.normalized}。请发一下联系电话。",
            "patch": {
                "official_delivery_address": candidate.normalized,
                "pending_delivery_address_candidate": None,
                "stage": "collecting_phone",
            },
        }

    def _reject_pending_address(self) -> dict:
        return {
            "agent": self.name,
            "handler": "reject_pending_address",
            "message": "好的，不用这个地址。你可以重新发配送地址。",
            "patch": {"pending_delivery_address_candidate": None, "stage": "collecting_address"},
        }
