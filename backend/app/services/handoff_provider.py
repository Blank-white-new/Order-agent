from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.enums import HandoffFailureCode, HandoffStatus


@dataclass(frozen=True)
class HandoffProviderResult:
    status: HandoffStatus
    failure_code: HandoffFailureCode | None = None
    resolution: dict[str, Any] | None = None


class HandoffProvider(Protocol):
    def request_handoff(self, _case) -> HandoffProviderResult: ...

    def cancel_handoff(self, _case) -> HandoffProviderResult: ...

    def get_status(self, case) -> HandoffProviderResult: ...

    def resolve(self, _case, resolution: dict[str, Any]) -> HandoffProviderResult: ...


class SimulationHandoffProvider:
    """No network, phone, employee, or external-agent integration is performed."""

    def request_handoff(self, _case) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus.PENDING)

    def cancel_handoff(self, _case) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus.CANCELLED, HandoffFailureCode.CASE_CANCELLED)

    def get_status(self, case) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus(case.status))

    def resolve(self, _case, resolution: dict[str, Any]) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus.RESOLVED, resolution=resolution)

    def simulate_assign(self, _case) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus.SIMULATED_AGENT_ASSIGNED)

    def simulate_connect(self, _case) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus.SIMULATED_AGENT_CONNECTED)

    def simulate_fail(self, _case, failure_code: HandoffFailureCode) -> HandoffProviderResult:
        return HandoffProviderResult(HandoffStatus.FAILED, failure_code=failure_code)
