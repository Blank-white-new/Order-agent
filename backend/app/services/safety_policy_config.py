from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True)
class SafetyPolicySettings:
    high_confidence: float = 0.85
    confirm_threshold: float = 0.65
    handoff_threshold: float = 0.35
    max_consecutive_misunderstandings: int = 2
    max_confirmation_failures: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.handoff_threshold <= self.confirm_threshold <= self.high_confidence <= 1:
            raise ValueError("Safety confidence thresholds must be ordered")
        if self.max_consecutive_misunderstandings < 1 or self.max_confirmation_failures < 1:
            raise ValueError("Safety counter thresholds must be positive")

    @classmethod
    def from_env(cls) -> "SafetyPolicySettings":
        return cls(
            high_confidence=_float_env("SAFETY_HIGH_CONFIDENCE", 0.85),
            confirm_threshold=_float_env("SAFETY_CONFIRM_THRESHOLD", 0.65),
            handoff_threshold=_float_env("SAFETY_HANDOFF_THRESHOLD", 0.35),
            max_consecutive_misunderstandings=_positive_int_env("MAX_CONSECUTIVE_MISUNDERSTANDINGS", 2),
            max_confirmation_failures=_positive_int_env("MAX_CONFIRMATION_FAILURES", 2),
        )
