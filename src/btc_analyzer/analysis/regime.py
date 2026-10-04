"""Causal trend and volatility classification using independent evidence."""

import numpy as np
import pandas as pd


def regimes(df: pd.DataFrame) -> pd.DataFrame:
    """Combine alignment, slope, long-term location and confirmed structure."""
    out = df.copy()
    bull = (
        (out.ema_alignment > 0.25).astype(int)
        + (out.ema_slope > 0.02).astype(int)
        + (out.price_vs_ema200 > 0).astype(int)
        + (out.structure == "Bullish Structure").astype(int)
    )
    bear = (
        (out.ema_alignment < -0.25).astype(int)
        + (out.ema_slope < -0.02).astype(int)
        + (out.price_vs_ema200 < 0).astype(int)
        + (out.structure == "Bearish Structure").astype(int)
    )
    out["regime"] = np.select(
        [bull >= 4, bear >= 4, bull >= 3, bear >= 3],
        ["Strong Uptrend", "Strong Downtrend", "Uptrend", "Downtrend"],
        default="Sideways",
    )
    group = (out.bars_since_gap == 1).cumsum()
    baseline = out.atr_pct.groupby(group).transform(
        lambda s: s.shift(1).rolling(100, min_periods=30).median()
    )
    width_baseline = out.bb_width.groupby(group).transform(
        lambda s: s.shift(1).rolling(100, min_periods=30).median()
    )
    ratio = (out.atr_pct / baseline.replace(0, np.nan) + out.bb_width / width_baseline.replace(0, np.nan)) / 2
    out["volatility_regime"] = np.select(
        [ratio >= 2.5, ratio >= 1.5, ratio <= 0.65],
        ["Extreme Volatility", "High Volatility", "Low Volatility"],
        default="Normal Volatility",
    )
    out["trend_direction"] = np.select([bull >= 3, bear >= 3], [1.0, -1.0], default=0.0)
    out.loc[out.ema_200.isna(), "trend_direction"] = np.nan
    return out
