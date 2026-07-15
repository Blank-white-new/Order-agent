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
