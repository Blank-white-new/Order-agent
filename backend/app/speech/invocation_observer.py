from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.speech.formats import ProviderMode


@dataclass
class ProviderInvocation:
    """Test/evaluation trace for one real Provider method invocation."""

    provider_name: str
    provider_mode: ProviderMode
    requires_network: bool
    operation: str
    fixture_id: str | None = None
    fixture_lookup_performed: bool = False
    fixture_found: bool | None = None
    hash_comparison_performed: bool = False
    hash_matched: bool | None = None
    metadata_comparison_performed: bool = False
    metadata_matched: bool | None = None
    success: bool = False
    error_code: str | None = None


class ProviderInvocationObserver:
    """Thread-safe collector kept outside speech business results."""

    def __init__(self) -> None:
        self._events: list[ProviderInvocation] = []
        self._lock = Lock()

    def record(self, event: ProviderInvocation) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> int:
        with self._lock:
            return len(self._events)

    def events_since(self, snapshot: int) -> tuple[ProviderInvocation, ...]:
        with self._lock:
            return tuple(self._events[snapshot:])

    @property
    def events(self) -> tuple[ProviderInvocation, ...]:
        return self.events_since(0)
