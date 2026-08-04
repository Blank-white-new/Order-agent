from __future__ import annotations

import math
import random
import statistics
from typing import Callable, Sequence


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summary(values: Sequence[float]) -> dict:
    materialized = [float(value) for value in values]
    if not materialized:
        return {"n": 0}
    return {
        "n": len(materialized),
        "mean": statistics.fmean(materialized),
        "median": statistics.median(materialized),
        "p25": percentile(materialized, 0.25),
        "p50": percentile(materialized, 0.50),
        "p75": percentile(materialized, 0.75),
        "iqr": percentile(materialized, 0.75) - percentile(materialized, 0.25),
        "p90": percentile(materialized, 0.90),
        "p95": percentile(materialized, 0.95),
        "p99": percentile(materialized, 0.99),
        "max": max(materialized),
        "standard_deviation": statistics.stdev(materialized) if len(materialized) > 1 else 0.0,
    }


def bootstrap_ci(
    values: Sequence,
    statistic: Callable[[list], float],
    *,
    resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    materialized = list(values)
    if not materialized:
        return {"estimate": None, "lower": None, "upper": None, "resamples": resamples}
    rng = random.Random(seed)
    n = len(materialized)
    estimates = [
        float(statistic([materialized[rng.randrange(n)] for _ in range(n)]))
        for _ in range(resamples)
    ]
    return {
        "estimate": float(statistic(materialized)),
        "lower": percentile(estimates, 0.025),
        "upper": percentile(estimates, 0.975),
        "resamples": resamples,
        "seed": seed,
    }


def relative_drift(values: Sequence[float]) -> float:
    materialized = [float(value) for value in values]
    if not materialized:
        return float("nan")
    center = statistics.fmean(materialized)
    if center == 0:
        return 0.0 if max(materialized) == 0 else float("inf")
    return (max(materialized) - min(materialized)) / center

