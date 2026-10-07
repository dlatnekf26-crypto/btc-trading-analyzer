import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.session_patterns import closed_hours, session_patterns
from btc_analyzer.ui.session_patterns import cached_patterns, pattern_cards

CUTOFF = pd.Timestamp("2026-10-06T12:00:00Z")


def candles(n=720):
    index = pd.date_range(end=CUTOFF - pd.Timedelta(hours=1), periods=n, freq="h", tz="UTC")
    close = 100000 + np.sin(np.arange(n) * np.pi / 2) * 200
    return pd.DataFrame({"open": 100000.0, "high": 100400.0, "low": 99600.0, "close": close}, index=index)


def test_recurring_band_counts_unique_hours_not_overlapping_windows():
    result = session_patterns(candles(), CUTOFF)
    band = result["range"]
    assert band["hours"] == band["observed"] == 72
    assert band["current_flat"]
    assert band["low"] == pytest.approx(99800)
    assert band["high"] == pytest.approx(100200)
    assert len(result["hours"]) == 24
    assert "중간 80%" in pattern_cards(result)


def test_trend_is_not_sideways_and_small_hour_samples_are_withheld():
    data = candles(72)
    data.close = 100000 * 1.003 ** np.arange(72)
    data.open = data.close / 1.003
    data.high = data.close * 1.001
    data.low = data.open * 0.999
    result = session_patterns(data, CUTOFF)
    assert result["range"] is None
    assert not result["hours"]
    assert "뚜렷한 반복 없음" in pattern_cards(result)


def test_closed_grid_ohlc_gaps_duplicates_and_future_data():
    data = candles(72)
    data.loc[data.index[0], "close"] = np.nan
    data.loc[data.index[1], "low"] = -1
    data.loc[data.index[2], "high"] = 1
    data = pd.concat([data, data.iloc[[3]]])
    partial = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]}, index=[CUTOFF])
    offgrid = partial.copy()
    offgrid.index -= pd.Timedelta(minutes=90)
    actual = closed_hours(pd.concat([data, partial, offgrid]), CUTOFF)
    assert len(actual) == 68
    assert actual.index.is_unique
    assert (actual.index + pd.Timedelta(hours=1) <= CUTOFF).all()
    # Sparse bars never form a six-hour contiguous range.
    assert session_patterns(candles(72).iloc[::2], CUTOFF)["range"] is None
    assert session_patterns(candles().iloc[:-1], CUTOFF)["range"] is None
    assert session_patterns(candles().tz_localize(None), CUTOFF)["bars"] == 0


def test_hour_open_in_kst_uses_intrabar_returns_not_gap_returns():
    data = candles()
    hour = data.index.tz_convert("Asia/Seoul").hour
    data.close = np.where(hour == 23, 101000.0, np.where(hour == 9, 99000.0, 100000.0))
    data.high, data.low = 102000.0, 98000.0
    result = session_patterns(data, CUTOFF)
    by_hour = {row["hour"]: row for row in result["hours"]}
    assert by_hour[23]["up"] == by_hour[23]["samples"] == 30
    assert by_hour[9]["down"] == 30
    assert by_hour[0]["flat"] == 30  # Midnight is not a fall from the preceding 23h candle.
    html = pattern_cards(result)
    assert "23~00시 KST" not in html and "09~10시 KST" not in html


def test_cache_changes_for_older_bar_revision_and_future_is_causal():
    cached_patterns.clear()
    data = candles()
    first = cached_patterns(data, CUTOFF)
    changed = data.copy()
    changed.iloc[0, changed.columns.get_loc("high")] = 1
    second = cached_patterns(changed, CUTOFF)
    assert first != second
    future = candles(1)
    future.index = pd.DatetimeIndex([CUTOFF + pd.Timedelta(hours=1)])
    assert session_patterns(pd.concat([data, future]), CUTOFF, include_hours=False) == first


def test_web_skips_removed_hour_statistics_and_keeps_the_same_sideways_range():
    original = session_patterns(candles(), CUTOFF)
    web = cached_patterns(candles(), CUTOFF)
    assert not web["hours"] and web["range"] == original["range"]
    html = pattern_cards(original)
    assert html.count('class="btc-pattern-card"') == 1
    assert "빈도가 가장" not in html and "움직임이 가장" not in html
