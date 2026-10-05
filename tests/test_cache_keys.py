"""Exact cache invalidation, including values lost by float conversion."""

import numpy as np
import pandas as pd

from btc_analyzer.ui.cache_keys import market_frame_key


def test_numeric_fingerprint_retains_every_row_dtype_integer_and_metadata():
    frame = pd.DataFrame(
        {"close": [100.0, 101.0], "large_integer": [2**54, 2**54 + 1], "flag": [True, False]},
        index=pd.date_range("2024-01-01", periods=2, tz="UTC"),
    )
    frame.attrs = {"timeframe": "1d", "ichimoku_displacement": 26, "quality": {"missing_candles": 0}}
    expected = market_frame_key(frame)
    assert market_frame_key(frame.copy(deep=True)) == expected
    changed = frame.copy()
    changed.iloc[0, 1] += 1
    assert market_frame_key(changed) != expected
    changed = frame.copy()
    changed.iloc[0, 0] = 100.00000001
    assert market_frame_key(changed) != expected
    changed = frame.copy()
    changed.index += pd.Timedelta(hours=1)
    assert market_frame_key(changed) != expected
    changed = frame.copy()
    changed.attrs["ichimoku_displacement"] = 27
    assert market_frame_key(changed) != expected
    changed = frame.copy()
    changed.attrs["quality"]["missing_candles"] = 1
    assert market_frame_key(changed) != expected
    changed = frame.copy()
    changed.attrs["cached"] = True
    assert market_frame_key(changed) == expected
    assert market_frame_key(frame.iloc[::-1]) != expected
    assert market_frame_key(frame.astype({"large_integer": "float64"})) != expected


def test_nulls_and_non_numeric_values_are_safe_and_changes_invalidate():
    frame = pd.DataFrame(
        {"price": [1.0, np.nan], "label": ["a", "b"], "count": pd.array([1, pd.NA], dtype="Int64")}
    )
    key = market_frame_key(frame)
    assert market_frame_key(frame.copy()) == key
    changed = frame.copy()
    changed.iloc[1, 1] = "c"
    assert market_frame_key(changed) != key


def test_nullable_integer_with_a_missing_value_keeps_bits_above_float_precision():
    frame = pd.DataFrame({"count": pd.array([2**54, pd.NA], dtype="Int64")})
    changed = frame.copy()
    changed.iloc[0, 0] += 1
    assert market_frame_key(frame) != market_frame_key(changed)
    assert market_frame_key(frame) == market_frame_key(frame.copy())
