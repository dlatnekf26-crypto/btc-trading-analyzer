"""Continuity and close times for 24/7 candles or an explicit exchange calendar."""

from functools import lru_cache

import numpy as np
import pandas as pd

from btc_analyzer.assets import SESSION_MARKETS

from btc_analyzer.candles import candle_close


@lru_cache(maxsize=24)
def session_index(epochs):
    """Immutable scalar tuples keep pandas metadata comparisons unambiguous."""
    return pd.to_datetime(epochs, unit="ns", utc=True)


def bar_closes(frame, times, timeframe):
    if frame.attrs.get("market") not in SESSION_MARKETS:
        return candle_close(times, timeframe)
    scalar = isinstance(times, pd.Timestamp)
    index = pd.DatetimeIndex([times] if scalar else times)
    positions = session_index(frame.attrs["bar_starts"]).get_indexer(index)
    if (positions < 0).any():
        raise ValueError("거래 세션에 없는 봉입니다.")
    closes = session_index(frame.attrs["bar_ends"])[positions]
    return closes[0] if scalar else closes


def gap_groups(frame, timeframe):
    if frame.attrs.get("market") in SESSION_MARKETS:
        positions = session_index(frame.attrs["bar_starts"]).get_indexer(frame.index)
        breaks = np.r_[True, (np.diff(positions) != 1) | (positions[1:] < 0)]
    else:
        breaks = np.r_[True, frame.index[1:] != candle_close(frame.index[:-1], timeframe)]
    return np.cumsum(breaks)


def shift_bars(frame, times, timeframe, periods):
    """Display shifts follow exchange sessions; projected clouds are not forecasts."""
    from btc_analyzer.candles import candle_shift

    if frame.attrs.get("market") not in SESSION_MARKETS:
        return candle_shift(times, timeframe, periods)
    index = pd.DatetimeIndex(times)
    starts = session_index(frame.attrs["bar_starts"])
    positions = starts.get_indexer(index)
    shifted = positions + periods
    if (positions < 0).any() or (shifted < 0).any() or (shifted >= len(starts)).any():
        from btc_analyzer.data.exchange_history import calendar_bars

        days = {"5m": 7, "15m": 7, "1h": 14, "4h": 28, "1d": 90, "1w": 400, "1M": 1000}[timeframe]
        starts, _ = calendar_bars(
            str((index.min() - pd.Timedelta(days=days)).date()),
            str((index.max() + pd.Timedelta(days=days)).date()),
            timeframe,
            frame.attrs["market"],
        )
        positions = starts.get_indexer(index)
        shifted = positions + periods
    if (positions < 0).any() or (shifted < 0).any() or (shifted >= len(starts)).any():
        raise ValueError("지표 표시용 거래 세션이 부족합니다.")
    return starts[shifted]
