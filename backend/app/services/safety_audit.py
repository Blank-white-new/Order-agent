from __future__ import annotations

import logging
import re
from typing import Any

from app.domain.errors import unsafe_audit_payload


logger = logging.getLogger("order_system.safety_audit")

FORBIDDEN_KEY_PARTS = (
    "phone",
    "address",
    "card",
    "pan",
    "transcript",
    "audio",
    "api_key",
    "secret",
    "prompt",
)

LONG_DIGIT_SEQUENCE = re.compile(r"(?<!\d)\d{8,19}(?!\d)")


def validate_safe_payload(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(part in normalized for part in FORBIDDEN_KEY_PARTS):
                raise unsafe_audit_payload()
            validate_safe_payload(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            validate_safe_payload(item, path=f"{path}[{index}]")
        return
    identifier_path = path.casefold().endswith("_id") or path.casefold().endswith("id")
    if isinstance(value, str):
        if "\r" in value or "\n" in value:
            raise unsafe_audit_payload()
        if not identifier_path and LONG_DIGIT_SEQUENCE.search(value):
            raise unsafe_audit_payload()


def log_safety_event(**fields: Any) -> None:
    validate_safe_payload(fields)
    ordered = " ".join(f"{key}={fields.get(key)}" for key in sorted(fields))
    logger.info("safety_event %s", ordered)
