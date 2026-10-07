"""Compare completed analogue paths by direction; shares are not calibrated odds."""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class DirectionScenario:
    key: str
    label: str
    share: float
    cases: int
    center: tuple[float, ...]
    assumed: bool = False


@dataclass(frozen=True)
class DirectionOutlook:
    scenarios: tuple[DirectionScenario, ...]
    leaders: tuple[str, ...]
    threshold: float
    cases: int
    effective_cases: float
    margin: float


def direction_outlook(result, projection=None):
    """Reuse ranked, disjoint analogues; never select a case by its future return.

    Compare their volatility-adjusted, unshrunk paths, optionally with the
    existing current-news price assumption. Manual release what-ifs do not rank
    directions. Missing directions get a labeled zero-share illustrative path.
    """
    report, prediction = result.history, result.prediction
    if prediction is None or len(prediction.weights) != len(report.matches):
        return None
    length = report.forward + 1
    base = np.asarray(prediction.center, dtype=float)
    if (
        length < 2
        or base.shape != (length,)
        or not np.isfinite(base).all()
        or np.any(base <= 0)
        or not math.isfinite(report.anchor_price)
        or report.anchor_price <= 0
        or not math.isfinite(report.volatility)
        or report.volatility < 0
    ):
        return None
    shown = np.asarray(projection.center if projection is not None else base, dtype=float)
    lower = np.asarray(projection.lower if projection is not None else prediction.lower, dtype=float)
    upper = np.asarray(projection.upper if projection is not None else prediction.upper, dtype=float)
    if any(
        values.shape != base.shape or not np.isfinite(values).all() or np.any(values <= 0)
        for values in (shown, lower, upper)
    ) or not np.isclose(shown[0], report.anchor_price):
        return None
    shift = np.log(shown / base)
    paths, weights = [], []
    for match, weight in zip(report.matches, prediction.weights):
        path = np.asarray(match.path[report.window - 1 :], dtype=float)
        if (
            path.shape != (length,)
            or not np.isfinite(path).all()
            or np.any(path <= 0)
            or not np.isclose(path[0], 100)
            or not math.isfinite(match.volatility)
            or match.volatility <= 0
            or not math.isfinite(weight)
            or weight <= 0
            or match.observed_until > report.query_start
        ):
            continue
        paths.append(np.log(path / 100) * np.clip(report.volatility / match.volatility, 0.5, 2) + shift)
        weights.append(weight)
    if len(paths) < 3:
        return None
    paths, weights = np.asarray(paths), np.asarray(weights)
    weights /= weights.sum()
    effective = float(1 / (weights @ weights))
    if effective < 2.5:
        return None
    paths[:, 0] = 0
    threshold = float(
        np.expm1(
            np.clip(0.25 * report.volatility * math.sqrt(report.forward), math.log1p(0.005), math.log1p(0.05))
        )
    )
    end = paths[:, -1]
    up, down = end > math.log1p(threshold) + 1e-12, end < math.log1p(-threshold) - 1e-12
    masks = (up, ~(up | down), down)
    progress = np.sqrt(np.linspace(0, 1, length))
    assumptions = (
        np.maximum(np.log(upper / report.anchor_price), math.log1p(threshold * 1.5) * progress),
        np.clip(np.log(shown / report.anchor_price), math.log1p(-threshold), math.log1p(threshold)),
        np.minimum(np.log(lower / report.anchor_price), math.log1p(-threshold * 1.5) * progress),
    )
    scenarios = []
    for (key, label), mask, assumption in zip(
        (("up", "상승"), ("flat", "보합"), ("down", "하락")), masks, assumptions
    ):
        cases, share = int(mask.sum()), float(weights[mask].sum())
        path = np.average(paths[mask], axis=0, weights=weights[mask]) if cases else assumption.copy()
        path[0] = 0
        scenarios.append(
            DirectionScenario(key, label, share, cases, tuple(report.anchor_price * np.exp(path)), not cases)
        )
    ranked = sorted((scenario.share for scenario in scenarios), reverse=True)
    leaders = tuple(scenario.key for scenario in scenarios if abs(scenario.share - ranked[0]) < 1e-9)
    return DirectionOutlook(
        tuple(scenarios), leaders, threshold, len(paths), effective, ranked[0] - ranked[1]
    )
