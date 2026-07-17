from __future__ import annotations

import pytest

from app.domain.errors import DomainError
from app.services.safety_audit import validate_safe_payload


@pytest.mark.parametrize(
    "payload",
    [
        {"phone": "+852 5555 0101"},
        {"deliveryAddress": "Synthetic Tower"},
        {"fullTranscript": "complete conversation"},
        {"cardNumber": "4111111111111111"},
        {"nested": {"audio": "raw"}},
        {"value": "4111111111111111"},
        {"api_key": "not-a-real-key"},
    ],
)
def test_audit_payload_rejects_sensitive_content(payload):
    with pytest.raises(DomainError) as error:
        validate_safe_payload(payload)
    assert error.value.code == "UNSAFE_AUDIT_PAYLOAD"


def test_audit_payload_allows_structured_codes_and_identifiers():
    validate_safe_payload(
        {
            "trace_id": "SIM-TRACE-1234567890",
            "session_id": "SIM-SESSION-1234567890",
            "reasonCode": "SEVERE_ALLERGY",
            "riskIds": ["RISK-013"],
            "blockedActions": ["SUBMIT_TO_MERCHANT"],
        }
    )
