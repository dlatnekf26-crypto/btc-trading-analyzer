"""Causal analogue forecasts with rolling, genuinely out-of-sample validation."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from btc_analyzer.analysis.historical_similarity import SimilarityReport, prepare_history
from btc_analyzer.candles import candle_close, candle_shift

MODEL_VERSION = "analogue-v1"
MIN_MATCHES = 3
MIN_CALIBRATION = 12
MAX_VALIDATION = 24


@dataclass(frozen=True)
class PriceForecast:
    dates: tuple[pd.Timestamp, ...]
    center: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    weights: tuple[float, ...]
    effective_cases: float
    rising_share: float
    calibrated_cases: int


@dataclass(frozen=True)
class ValidationCase:
    origin: pd.Timestamp
    observed_until: pd.Timestamp
    predicted_return: float
    actual_return: float
    lower_return: float
    upper_return: float
    calibration_cases: int


@dataclass(frozen=True)
class ForecastReport:
    history: SimilarityReport
    prediction: PriceForecast | None
    reason: str | None
    validation: tuple[ValidationCase, ...]
    mae: float | None
    baseline_mae: float | None
    directional_accuracy: float | None
    coverage: float | None


def forecast_path(report: SimilarityReport, errors=()) -> PriceForecast | None:
    """Similarity weights + volatility scaling; bands are estimates, not promises.

    Errors must come from completed predictions made strictly before this origin.
    Each vector contains absolute log-price errors across the same horizon.
    """
    if len(report.matches) < MIN_MATCHES:
        return None
    scores = np.array([match.similarity for match in report.matches])
    weights = np.exp((scores - scores.max()) / 10)
    weights /= weights.sum()
    effective = float(1 / (weights @ weights))
    if effective < 2.5:
        return None
    scenarios = np.array([np.log(np.array(m.path[report.window - 1 :]) / 100) for m in report.matches])
    scale = np.clip(report.volatility / np.array([m.volatility for m in report.matches]), 0.5, 2)
    scenarios *= scale[:, None]
    # Small or weak samples shrink the predicted move towards unchanged price.
    reliability = min(0.85, float(weights @ scores / 100)) * min(1, (effective - 1) / 4)
    center = weights @ scenarios * reliability
    order = np.argsort(scenarios, axis=0)
    ranked = np.take_along_axis(scenarios, order, axis=0)
    ranked_weights = weights[order]
    cumulative = np.cumsum(ranked_weights, axis=0) - ranked_weights / 2
    quantiles = np.array(
        [
            [np.interp(q, cumulative[:, step], ranked[:, step]) for step in range(report.forward + 1)]
            for q in (0.1, 0.9)
        ]
    )
    radius = 1.281552 * report.volatility * np.sqrt(np.arange(report.forward + 1))
    calibrated = len(errors) if len(errors) >= MIN_CALIBRATION else 0
    if calibrated:
        radius = np.maximum(radius, np.quantile(np.array(errors), 0.8, axis=0))
    lower = np.minimum(quantiles[0], center - radius)
    upper = np.maximum(quantiles[1], center + radius)
    # Anchor all lines to the same observed, closed-candle price.
    center[0] = lower[0] = upper[0] = 0
    prices = report.anchor_price * np.exp(np.stack([center, lower, upper]))
    return PriceForecast(
        tuple(candle_shift(report.query_end, report.timeframe, i) for i in range(report.forward + 1)),
        tuple(prices[0]),
        tuple(prices[1]),
        tuple(prices[2]),
        tuple(weights),
        effective,
        float(weights @ (scenarios[:, -1] > 0)),
        calibrated,
    )


def predict_history(raw, timeframe, as_of, window=30, forward=30, *, min_similarity=60) -> ForecastReport:
    prepared = prepare_history(raw, timeframe, as_of, window, forward, min_similarity=min_similarity)
    current = prepared.compare(forward, min_similarity=min_similarity)
    first = forecast_path(current)
    if first is None:
        return ForecastReport(
            current,
            None,
            "서로 겹치지 않는 유사 사례가 3개 이상이고 가중 유효 사례가 2.5개 이상이어야 예측합니다.",
            (),
            None,
            None,
            None,
            None,
        )
    frame = prepared.frame
    # Outcomes are disjoint; complete at/before the current confirmed close.
    origins = list(range(len(frame) - 1 - forward, window - 2, -forward))[:MAX_VALIDATION]
    cases, errors = [], []
    for origin in reversed(origins):
        if prepared.gaps[origin + forward] != prepared.gaps[origin]:
            continue
        try:
            historical = prepared.compare(forward, query_end=origin, min_similarity=min_similarity)
        except ValueError:
            continue
        prediction = forecast_path(historical, errors)
        if prediction is None:
            continue
        actual_path = prepared.close[origin : origin + forward + 1] / prepared.close[origin]
        predicted_path = np.array(prediction.center) / historical.anchor_price
        cases.append(
            ValidationCase(
                historical.query_end,
                candle_close(frame.index[origin + forward], timeframe),
                float(predicted_path[-1] - 1),
                float(actual_path[-1] - 1),
                float(prediction.lower[-1] / historical.anchor_price - 1),
                float(prediction.upper[-1] / historical.anchor_price - 1),
                prediction.calibrated_cases,
            )
        )
        # Add this outcome only AFTER forecasting this origin. At the next
        # origin, its last candle is closed and the error is observable.
        errors.append(np.abs(np.log(actual_path) - np.log(predicted_path)))
    prediction = forecast_path(current, errors)
    mae = float(np.mean([abs(c.predicted_return - c.actual_return) for c in cases])) if cases else None
    baseline = float(np.mean([abs(c.actual_return) for c in cases])) if cases else None
    direction_cases = [c for c in cases if abs(c.actual_return) >= 0.005]
    accuracy = (
        float(
            np.mean(
                [
                    (1 if c.predicted_return >= 0.005 else -1 if c.predicted_return <= -0.005 else 0)
                    == (1 if c.actual_return > 0 else -1)
                    for c in direction_cases
                ]
            )
        )
        if direction_cases
        else None
    )
    calibrated_cases = [c for c in cases if c.calibration_cases >= MIN_CALIBRATION]
    coverage = (
        float(np.mean([c.lower_return <= c.actual_return <= c.upper_return for c in calibrated_cases]))
        if calibrated_cases
        else None
    )
    return ForecastReport(current, prediction, None, tuple(cases), mae, baseline, accuracy, coverage)
