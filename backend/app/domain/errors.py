from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus


@dataclass(eq=False)
class DomainError(Exception):
    code: str
    message: str
    http_status: int = HTTPStatus.CONFLICT

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def tenant_context_mismatch() -> DomainError:
    return DomainError("TENANT_CONTEXT_MISMATCH", "The session is bound to a different tenant context.")


def restaurant_not_found() -> DomainError:
    return DomainError("RESTAURANT_NOT_FOUND", "Restaurant context was not found.", HTTPStatus.NOT_FOUND)


def branch_not_found() -> DomainError:
    return DomainError("BRANCH_NOT_FOUND", "Branch context was not found.", HTTPStatus.NOT_FOUND)


def no_published_menu() -> DomainError:
    return DomainError("NO_PUBLISHED_MENU", "No published menu is available for this branch.", HTTPStatus.UNPROCESSABLE_ENTITY)


def item_unavailable(*, sold_out: bool = False) -> DomainError:
    code = "ITEM_SOLD_OUT" if sold_out else "ITEM_UNAVAILABLE"
    return DomainError(code, "The requested menu item is not currently available.")


def invalid_order_transition(current: str, target: str) -> DomainError:
    return DomainError("INVALID_ORDER_TRANSITION", f"Order cannot transition from {current} to {target}.")


def confirmation_stale() -> DomainError:
    return DomainError("CONFIRMATION_STALE", "The confirmation does not match the current draft version.")


def idempotency_conflict() -> DomainError:
    return DomainError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different request.")


def simulation_data_required() -> DomainError:
    return DomainError("SIMULATION_DATA_REQUIRED", "Only explicitly synthetic data is accepted in this environment.", HTTPStatus.UNPROCESSABLE_ENTITY)


def database_write_failed() -> DomainError:
    return DomainError("DATABASE_WRITE_FAILED", "The change could not be saved.", HTTPStatus.SERVICE_UNAVAILABLE)


def session_version_conflict() -> DomainError:
    return DomainError("SESSION_VERSION_CONFLICT", "The session was changed by another request.")


def session_closed() -> DomainError:
    return DomainError("SESSION_CLOSED", "The session is closed and cannot be modified.")


def menu_publish_conflict() -> DomainError:
    return DomainError(
        "MENU_PUBLISH_CONFLICT",
        "Another menu publication won the restaurant-wide publication race.",
    )


def modifier_required(group_code: str) -> DomainError:
    return DomainError(
        "MODIFIER_REQUIRED",
        f"A required modifier selection is missing for group '{group_code}'.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def modifier_too_few(group_code: str) -> DomainError:
    return DomainError(
        "MODIFIER_TOO_FEW",
        f"Too few modifier selections were provided for group '{group_code}'.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def modifier_too_many(group_code: str) -> DomainError:
    return DomainError(
        "MODIFIER_TOO_MANY",
        f"Too many modifier selections were provided for group '{group_code}'.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def modifier_not_available() -> DomainError:
    return DomainError(
        "MODIFIER_NOT_AVAILABLE",
        "A selected modifier is not available for this menu item.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def modifier_ambiguous() -> DomainError:
    return DomainError(
        "MODIFIER_AMBIGUOUS",
        "A modifier name matches more than one group; use an unambiguous selection.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def modifier_duplicate() -> DomainError:
    return DomainError(
        "MODIFIER_DUPLICATE",
        "The same modifier option cannot be selected more than once.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def safety_session_not_found() -> DomainError:
    return DomainError("SAFETY_SESSION_NOT_FOUND", "The requested safety context was not found.", HTTPStatus.NOT_FOUND)


def handoff_not_found() -> DomainError:
    return DomainError("HANDOFF_NOT_FOUND", "The simulated handoff case was not found.", HTTPStatus.NOT_FOUND)


def invalid_handoff_transition(current: str, target: str) -> DomainError:
    return DomainError(
        "INVALID_HANDOFF_TRANSITION",
        f"The simulated handoff cannot transition from {current} to {target}.",
    )


def simulation_controls_disabled() -> DomainError:
    return DomainError(
        "SIMULATION_CONTROLS_DISABLED",
        "Simulation controls are not available in this environment.",
        HTTPStatus.NOT_FOUND,
    )


def unsafe_audit_payload() -> DomainError:
    return DomainError(
        "UNSAFE_AUDIT_PAYLOAD",
        "The audit payload contains a prohibited field.",
        HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def safety_hold_active() -> DomainError:
    return DomainError("SAFETY_HOLD_ACTIVE", "The order is blocked by an active safety decision.")
