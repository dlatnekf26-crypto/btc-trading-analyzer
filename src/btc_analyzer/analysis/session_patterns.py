"""Descriptive ranges and KST hour statistics from closed, validated hourly bars."""

import numpy as np
import pandas as pd

HOUR = pd.Timedelta(hours=1)
NEUTRAL_RETURN = 0.0015
MIN_HOUR_SAMPLES = 20


def closed_hours(frame, cutoff):
    cutoff = pd.Timestamp(cutoff)
    columns = ["open", "high", "low", "close"]
    if (
        cutoff.tzinfo is None
        or not isinstance(frame, pd.DataFrame)
        or not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is None
        or not set(columns).issubset(frame.columns)
    ):
        return pd.DataFrame(columns=columns)
    cutoff = cutoff.tz_convert("UTC").floor("h")
    data = frame[columns].copy()
    data.index = data.index.tz_convert("UTC")
    data = data.loc[~data.index.duplicated(keep=False)].sort_index()
    data = data.apply(pd.to_numeric, errors="coerce")
    grid = data.index == data.index.floor("h")
    values = data.to_numpy(dtype=float)
    valid = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
    valid &= data.high.ge(data[["open", "close", "low"]].max(axis=1)).to_numpy()
    valid &= data.low.le(data[["open", "close", "high"]].min(axis=1)).to_numpy()
    return data.loc[
        valid & grid & (data.index + HOUR <= cutoff) & (data.index >= cutoff - pd.Timedelta(days=30))
    ]


def session_patterns(frame, cutoff, *, include_hours=True):
    data = closed_hours(frame, cutoff)
    result = {"hours": [], "range": None, "bars": len(data), "start": None, "end": None}
    if data.empty:
        return result
    result.update(start=data.index[0], end=data.index[-1] + HOUR)
    if include_hours:
        returns = data.close / data.open - 1
        kst_hours = data.index.tz_convert("Asia/Seoul").hour
        for hour in range(24):
            sample = returns.loc[kst_hours == hour]
            if len(sample) < MIN_HOUR_SAMPLES:
                continue
            result["hours"].append(
                {
                    "hour": hour,
                    "samples": len(sample),
                    "up": int((sample > NEUTRAL_RETURN).sum()),
                    "down": int((sample < -NEUTRAL_RETURN).sum()),
                    "flat": int((sample.abs() <= NEUTRAL_RETURN).sum()),
                    "median_move": float(sample.abs().median()),
                }
            )
    cutoff = pd.Timestamp(cutoff).tz_convert("UTC").floor("h")
    recent = data.loc[data.index >= cutoff - pd.Timedelta(hours=72)]
    # Old quotes must not be described as the current market.
    if len(recent) < 12 or recent.index[-1] + HOUR != cutoff:
        return result
    current = float(recent.close.iloc[-1])
    spread_limit = float(np.clip(3 * (recent.high / recent.low - 1).median(), 0.02, 0.04))
    selected, current_flat = set(), False
    for end in range(6, len(recent) + 1):
        window = recent.iloc[end - 6 : end]
        if not window.index.to_series().diff().iloc[1:].eq(HOUR).all():
            continue
        low, high = float(window.low.min()), float(window.high.max())
        closes = window.close.to_numpy()
        travel = float(np.abs(np.diff(closes)).sum())
        net = abs(float(closes[-1] - closes[0]))
        weak_direction = travel == 0 or net / travel <= 0.3 or net / closes[0] <= 0.0025
        flat = weak_direction and high / low - 1 <= spread_limit
        if end == len(recent):
            current_flat = flat
        if flat and low <= current <= high and abs((low + high) / (2 * current) - 1) <= 0.01:
            selected.update(range(end - 6, end))
    # Count unique hours, never overlapping windows as independent occurrences.
    if len(selected) >= 12:
        observations = recent.iloc[sorted(selected)].close
        low, high = observations.quantile([0.1, 0.9]).to_numpy()
        if high / low - 1 <= 0.04:
            result["range"] = {
                "low": float(low),
                "high": float(high),
                "hours": len(selected),
                "observed": len(recent),
                "current_flat": current_flat,
            }
    return result
