"""Strict, confirmed swing pivots recorded at their confirmation timestamp."""

import numpy as np
import pandas as pd
from btc_analyzer.config import IndicatorConfig


def market_structure(df: pd.DataFrame, cfg: IndicatorConfig | None = None) -> pd.DataFrame:
    """A pivot at N becomes visible at N+right. No backdating or repainting.

    Ties are excluded. HH/HL etc compare the latest two confirmed pivots.
    Confirmation state expires after structure_window bars and resets at gaps.
    """
    cfg = cfg or IndicatorConfig()
    out = df.copy()
    left, right = cfg.pivot_left, cfg.pivot_right
    high_candidate, low_candidate = df.high.shift(right), df.low.shift(right)
    before_high = df.high.shift(right + 1).rolling(left).max()
    before_low = df.low.shift(right + 1).rolling(left).min()
    after_high = df.high.rolling(right).max()
    after_low = df.low.rolling(right).min()
    enough = df.bars_since_gap > left + right
    out["pivot_high"] = high_candidate.where(
        enough & (high_candidate > before_high) & (high_candidate > after_high)
    )
    out["pivot_low"] = low_candidate.where(
        enough & (low_candidate < before_low) & (low_candidate < after_low)
    )
    groups = (df.bars_since_gap == 1).cumsum()
    for kind in ("high", "low"):
        pivot = out[f"pivot_{kind}"]
        last = pivot.groupby(groups).ffill(limit=cfg.structure_window)
        previous = pd.Series(np.nan, index=df.index)
        for _, idx in df.groupby(groups).groups.items():
            events = pivot.loc[idx].dropna()
            previous.loc[idx] = events.shift(1).reindex(idx).ffill(limit=cfg.structure_window)
        out[f"last_swing_{kind}"] = last
        out[f"previous_swing_{kind}"] = previous
    high_delta = out.last_swing_high - out.previous_swing_high
    low_delta = out.last_swing_low - out.previous_swing_low
    out["hh"] = high_delta > 0
    out["lh"] = high_delta < 0
    out["hl"] = low_delta > 0
    out["ll"] = low_delta < 0
    out["structure"] = np.select(
        [out.hh & out.hl, out.lh & out.ll, (out.hh & out.ll) | (out.lh & out.hl)],
        ["Bullish Structure", "Bearish Structure", "Possible Transition"],
        default="Range",
    )
    return out
