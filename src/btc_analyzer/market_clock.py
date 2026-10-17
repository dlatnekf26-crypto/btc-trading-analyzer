"""Continuity and close times for 24/7 candles or an explicit exchange calendar."""

from functools import lru_cache

import numpy as np
import pandas as pd

from btc_analyzer.candles import candle_close


@lru_cache(maxsize=24)
def session_index(epochs):
    """Immutable scalar tuples keep pandas metadata comparisons unambiguous."""
    return pd.to_datetime(epochs, unit="ns", utc=True)


def bar_closes(frame, times, timeframe):
    if frame.attrs.get("market") != "NQ":
        return candle_close(times, timeframe)
    scalar = isinstance(times, pd.Timestamp)
    index = pd.DatetimeIndex([times] if scalar else times)
    positions = session_index(frame.attrs["bar_starts"]).get_indexer(index)
    if (positions < 0).any():
        raise ValueError("거래 세션에 없는 봉입니다.")
    closes = session_index(frame.attrs["bar_ends"])[positions]
    return closes[0] if scalar else closes


def gap_groups(frame, timeframe):
    if frame.attrs.get("market") == "NQ":
        positions = session_index(frame.attrs["bar_starts"]).get_indexer(frame.index)
        breaks = np.r_[True, (np.diff(positions) != 1) | (positions[1:] < 0)]
    else:
        breaks = np.r_[True, frame.index[1:] != candle_close(frame.index[:-1], timeframe)]
    return np.cumsum(breaks)
