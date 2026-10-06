"""Conditional correction timing from completed analogues, not calibrated odds."""

from dataclasses import dataclass
from datetime import datetime
import math

import numpy as np
import pandas as pd

from btc_analyzer.analysis.news_projection import FRAME_DAYS


@dataclass(frozen=True)
class CorrectionOutlook:
    threshold: float
    trigger_price: float
    cases: int
    hits: int
    share: float | None
    window_start: pd.Timestamp | None = None
    window_end: pd.Timestamp | None = None
    low: float | None = None
    high: float | None = None
    reason: str = ""


def sample_quantile(values, weights, q):
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order]) / weights.sum()
    return values[order[min(np.searchsorted(cumulative, q), len(order) - 1)]]


def correction_outlook(result, threshold=0.05):
    if threshold not in (0.03, 0.05, 0.10):
        raise ValueError("Unsupported correction threshold")
    report, prediction = result.history, result.prediction
    trigger = report.anchor_price * (1 - threshold)
    unavailable = CorrectionOutlook(
        threshold, trigger, 0, 0, None, reason="유효한 유사 사례가 부족해 조정 시점을 추정하지 않아요."
    )
    if prediction is None:
        return unavailable
    paths, weights = [], []
    for match, weight in zip(report.matches, prediction.weights):
        path = np.array(match.path[report.window - 1 :], dtype=float)
        if (
            len(path) != len(prediction.dates)
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
        scale = np.clip(report.volatility / match.volatility, 0.5, 2)
        paths.append(report.anchor_price * np.exp(np.log(path / 100) * scale))
        weights.append(weight)
    if len(paths) < 3:
        return unavailable
    paths, weights = np.asarray(paths), np.asarray(weights)
    weights /= weights.sum()
    if 1 / (weights @ weights) < 2.5:
        return unavailable
    reached = paths[:, 1:] <= trigger
    hit = reached.any(axis=1)
    count = int(hit.sum())
    share = float(np.clip(weights @ hit, 0, 1))
    if count < 2:
        return CorrectionOutlook(
            threshold,
            trigger,
            len(paths),
            count,
            share,
            reason="하락 사례가 2개 미만이라 시점·가격 구간은 추정하지 않아요.",
        )
    first = reached[hit].argmax(axis=1) + 1
    start = max(0, int(sample_quantile(first, weights[hit], 0.25)) - 1)
    end = int(sample_quantile(first, weights[hit], 0.75))
    lows = paths[hit, 1:].min(axis=1)
    return CorrectionOutlook(
        threshold,
        trigger,
        len(paths),
        count,
        share,
        prediction.dates[start],
        prediction.dates[end],
        float(sample_quantile(lows, weights[hit], 0.25)),
        float(sample_quantile(lows, weights[hit], 0.75)),
    )


@dataclass(frozen=True)
class TechnicalEvidence:
    pressure: int
    reasons: tuple[str, ...]


def technical_evidence(values):
    def number(key):
        value = values.get(key)
        try:
            return float(value) if math.isfinite(float(value)) else None
        except (TypeError, ValueError):
            return None

    pressure, reasons = 0, []
    rsi, hist, close, ema = (number(key) for key in ("rsi", "macd_hist", "close", "ema_20"))
    if rsi is not None and 0 <= rsi <= 100:
        pressure += 1 if rsi >= 70 else -1 if rsi <= 30 else 0
        reasons.append(
            f"RSI {rsi:.1f} · "
            + (
                "매수 과열, 되돌림에 주의"
                if rsi >= 70
                else "매도 과열, 반등 여지는 있으나 추가 하락 가능"
                if rsi <= 30
                else "과열 구간 아님"
            )
        )
    if hist is not None:
        pressure += 1 if hist < 0 else -1 if hist > 0 else 0
        reasons.append(
            "MACD · "
            + (
                "기준선 아래, 흐름 약화"
                if hist < 0
                else "기준선 위, 흐름 지지"
                if hist > 0
                else "기준선과 같음"
            )
        )
    if close is not None and ema is not None and close > 0 and ema > 0:
        pressure += 1 if close < ema else -1 if close > ema else 0
        reasons.append(
            f"종가가 EMA20 {'아래' if close < ema else '위' if close > ema else '동일'} · {close / ema - 1:+.1%}"
        )
    return TechnicalEvidence(pressure, tuple(reasons))


@dataclass(frozen=True)
class EventProjection:
    center: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    shift: float
    event_at: datetime
    condition: str
    max_move: float


def project_event(result, base, event, now, condition, pressure=0):
    """Unvalidated what-if; consensus does not imply an anticipated surprise."""
    if condition == "neutral" or result.prediction is None:
        return None
    if condition not in ("adverse", "favorable"):
        raise ValueError("Unknown release condition")
    dates = result.prediction.dates
    if event.at <= max(now, dates[0].to_pydatetime()) or event.at >= dates[-1].to_pydatetime():
        return None
    sign = -1 if condition == "adverse" else 1
    sigma = result.history.volatility / math.sqrt(FRAME_DAYS[result.history.timeframe])
    unit = float(np.clip(sigma * 0.5, 0.0025, 0.02))
    shock = min(0.03, unit * (1 - sign * 0.15 * np.clip(pressure, -3, 3)))
    elapsed = np.maximum(
        0, np.array([(date.to_pydatetime() - event.at).total_seconds() / 86400 for date in dates])
    )
    response = (1 - np.exp(-elapsed)) * np.exp(-elapsed / 7)
    shift = sign * shock * response
    center = np.asarray(base.center) * np.exp(shift)
    lower = np.minimum(base.lower, np.asarray(base.lower) * np.exp(shift - unit * response))
    upper = np.maximum(base.upper, np.asarray(base.upper) * np.exp(shift + unit * response))
    return EventProjection(
        tuple(center),
        tuple(lower),
        tuple(upper),
        float(np.expm1(shift[-1])),
        event.at,
        condition,
        float(np.max(np.abs(np.expm1(shift)))),
    )
