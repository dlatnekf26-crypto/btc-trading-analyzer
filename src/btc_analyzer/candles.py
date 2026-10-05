"""UTC candle boundaries: Binance weeks start Monday, months start on day one."""

import pandas as pd

from btc_analyzer.config import TIMEFRAMES


def candle_boundary(value: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    """Latest closed-candle boundary, including calendar weeks and months."""
    if timeframe == "1M":
        return value.normalize().replace(day=1)
    if timeframe == "1w":
        return value.normalize() - pd.Timedelta(days=value.dayofweek)
    return value.floor(pd.Timedelta(seconds=TIMEFRAMES[timeframe]))


def candle_close(value, timeframe: str):
    """Next opening boundary, not an approximate 30-day month."""
    if timeframe == "1M":
        return value + pd.offsets.MonthBegin(1)
    return value + pd.Timedelta(seconds=TIMEFRAMES[timeframe])


def candle_shift(value, timeframe: str, periods: int):
    """Move plotted candle coordinates, preserving actual month boundaries."""
    if timeframe == "1M":
        return value + pd.offsets.MonthBegin(periods)
    return value + pd.Timedelta(seconds=TIMEFRAMES[timeframe] * periods)


def history_start(value: pd.Timestamp, timeframe: str, bars: int) -> pd.Timestamp:
    if timeframe == "1M":
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - pd.DateOffset(months=bars)
    return value - pd.Timedelta(seconds=TIMEFRAMES[timeframe] * bars)


def candle_grid(values: pd.Series, timeframe: str) -> pd.Series:
    if timeframe in ("1w", "1M"):
        midnight = values == values.dt.normalize()
        return midnight & ((values.dt.day == 1) if timeframe == "1M" else (values.dt.dayofweek == 0))
    duration = pd.Timedelta(seconds=TIMEFRAMES[timeframe])
    timestamps = pd.DatetimeIndex(values).as_unit("ns").asi8
    return pd.Series(values.notna().to_numpy() & (timestamps % duration.value == 0), index=values.index)


def missing_intervals(index: pd.DatetimeIndex, timeframe: str) -> pd.Series:
    if timeframe == "1M":
        ordinal = pd.Series(index.year * 12 + index.month, index=index)
        return ordinal.diff().sub(1).clip(lower=0).fillna(0)
    duration = pd.Timedelta(seconds=TIMEFRAMES[timeframe])
    return index.to_series().diff().div(duration).sub(1).clip(lower=0).fillna(0)


def resample_candles(raw: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule = {"1w": "W-MON", "1M": "MS"}.get(timeframe, pd.Timedelta(seconds=TIMEFRAMES[timeframe]))
    return (
        raw.resample(rule, origin="epoch", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
