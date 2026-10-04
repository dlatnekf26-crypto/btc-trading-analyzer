"""Feature preparation and as-of joining on candle CLOSE/availability time."""

import numpy as np
import pandas as pd
from btc_analyzer.config import AppConfig, TIMEFRAMES, MTF_MAP
from btc_analyzer.candles import candle_close
from btc_analyzer.indicators.core import indicators
from btc_analyzer.analysis.market_structure import market_structure
from btc_analyzer.analysis.regime import regimes


def enrich(df: pd.DataFrame, timeframe: str, cfg: AppConfig | None = None) -> pd.DataFrame:
    """Compute single-timeframe features; all columns are prefix invariant."""
    cfg = cfg or AppConfig()
    return regimes(market_structure(indicators(df, cfg.indicators, timeframe), cfg.indicators))


def prepare(bundle: dict[str, pd.DataFrame], timeframe: str, cfg: AppConfig | None = None) -> pd.DataFrame:
    """Join higher/lower trends available by each current candle close.

    No backfill. Max age = one higher period, so missing/stale higher candles
    stop providing confirmation. A 4h candle opening 00:00 cannot influence
    the 1h candle closing 01:00; it first becomes available at 04:00.
    """
    cfg = cfg or AppConfig()
    if timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported timeframe")
    if timeframe not in bundle:
        raise ValueError("Current timeframe missing")
    frames = {tf: enrich(data, tf, cfg) for tf, data in bundle.items() if not data.empty}
    if timeframe not in frames:
        raise ValueError("No closed candles for current timeframe")
    base = frames[timeframe].copy()
    out = base.assign(available_at=candle_close(base.index, timeframe))
    out = out.reset_index()
    for tf, frame in frames.items():
        if tf == timeframe:
            continue
        period = pd.Timedelta(seconds=TIMEFRAMES[tf])
        higher = pd.DataFrame(
            {
                "available_at": candle_close(frame.index, tf),
                "_valid_until": candle_close(candle_close(frame.index, tf), tf),
                f"trend_{tf}": frame.trend_direction.to_numpy(),
                f"regime_{tf}": frame.regime.to_numpy(),
                f"close_{tf}": frame.close.to_numpy(),
            }
        )
        out = pd.merge_asof(
            out.sort_values("available_at"),
            higher.sort_values("available_at"),
            on="available_at",
            direction="backward",
            tolerance=pd.Timedelta(days=32) if tf == "1M" else period,
        )
        expired = out.available_at >= out._valid_until
        for column in (f"trend_{tf}", f"regime_{tf}", f"close_{tf}"):
            out.loc[expired, column] = None if column.startswith("regime_") else np.nan
        out = out.drop(columns="_valid_until")
    # Missing higher frames still count in the denominator. Otherwise absent
    # macro data falsely reports 100% coverage, or the current trend confirms itself.
    higher_tfs = sorted(
        {tf for tf in (*MTF_MAP[timeframe], *frames) if TIMEFRAMES[tf] > TIMEFRAMES[timeframe]},
        key=TIMEFRAMES.__getitem__,
    )
    for tf in higher_tfs:
        if tf not in frames:
            out[f"trend_{tf}"] = np.nan
            out[f"regime_{tf}"] = None
            out[f"close_{tf}"] = np.nan
    if higher_tfs:
        weights = np.array([np.sqrt(TIMEFRAMES[tf] / TIMEFRAMES[timeframe]) for tf in higher_tfs])
        cols = [f"trend_{tf}" for tf in higher_tfs]
        values = out[cols].to_numpy(dtype=float)
        # Unknown higher trends contribute neutral, NOT fictitious confirmation.
        out["higher_trend"] = np.nansum(values * weights, axis=1) / weights.sum()
        out["higher_coverage"] = np.isfinite(values).sum(axis=1) / len(cols)
    else:
        out["higher_trend"], out["higher_coverage"] = out.trend_direction, 1.0
    out = out.set_index("timestamp")
    out.attrs = dict(base.attrs)
    out.attrs["timeframe"] = timeframe
    return out
