"""Small causal descriptors for matching momentum, trend strength and money flow."""

import numpy as np
import pandas as pd

CONTEXT_LABELS = ("RSI 14", "ADX 14", "CMF 20")
CONTEXT_SCALES = np.array([25.0, 25.0, 0.3])


def seeded_wilder(series: pd.Series, length: int) -> pd.Series:
    """SMA seed followed by compiled EWM on one contiguous finite segment."""
    result = pd.Series(np.nan, index=series.index)
    finite = np.flatnonzero(series.notna().to_numpy())
    if len(finite) < length:
        return result
    start = finite[0]
    seed = start + length - 1
    tail = series.iloc[seed:].copy()
    tail.iloc[0] = series.iloc[start : seed + 1].mean()
    result.iloc[seed:] = tail.ewm(alpha=1 / length, adjust=False).mean()
    return result


def momentum(close):
    delta = close.diff()
    gain = seeded_wilder(delta.clip(lower=0), 14)
    loss = seeded_wilder(-delta.clip(upper=0), 14)
    value = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    value = value.mask((loss == 0) & (gain > 0), 100)
    value = value.mask((gain == 0) & (loss > 0), 0)
    return value.mask((gain == 0) & (loss == 0), 50)


def context_indicators(frame: pd.DataFrame, gaps: np.ndarray) -> np.ndarray:
    """Reset all warmups after gaps; no global fitting or future normalization."""
    result = np.full((len(frame), 3), np.nan)
    boundaries = np.r_[0, np.flatnonzero(np.diff(gaps)) + 1, len(frame)]
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        segment = frame.iloc[start:end]
        up, down = segment.high.diff(), -segment.low.diff()
        plus = up.where((up > down) & (up > 0), 0.0).mask(up.isna())
        minus = down.where((down > up) & (down > 0), 0.0).mask(down.isna())
        smoothed_plus, smoothed_minus = seeded_wilder(plus, 14), seeded_wilder(minus, 14)
        denominator = smoothed_plus + smoothed_minus
        # ATR cancels from |DI+ - DI-| / (DI+ + DI-). Flat movement is zero DX.
        dx = (100 * (smoothed_plus - smoothed_minus).abs() / denominator.replace(0, np.nan)).mask(
            denominator == 0, 0.0
        )
        spread = segment.high - segment.low
        multiplier = ((2 * segment.close - segment.high - segment.low) / spread.replace(0, np.nan)).mask(
            spread == 0, 0.0
        )
        flow = (multiplier * segment.volume).rolling(20).sum()
        volume = segment.volume.rolling(20).sum().replace(0, np.nan)
        result[start:end] = np.column_stack([momentum(segment.close), seeded_wilder(dx, 14), flow / volume])
    return result
