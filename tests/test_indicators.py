"""Independent recurrence/reference tests for the important numerical calculations."""

import numpy as np
import pandas as pd
import pytest
from btc_analyzer.indicators.core import ema, rsi, macd, atr, bollinger, indicators, wilder


def test_ema_recurrence():
    s = pd.Series([1.0, 2.0, 4.0, 8.0, 16.0])
    value = s.iloc[0]
    expected = []
    for x in s:
        value = 0.5 * x + 0.5 * value
        expected.append(value)
    result = ema(s, 3)
    assert result.iloc[:2].isna().all()
    np.testing.assert_allclose(result.iloc[2:], expected[2:])


def test_rsi_known_wilder_example():
    # Wilder's published 14-period example; initial average gains .23857 / losses .1.
    s = pd.Series(
        [
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
            46.00,
        ]
    )
    assert rsi(s, 14).iloc[14] == pytest.approx(70.464135, abs=0.00001)
    assert rsi(pd.Series(np.arange(30, dtype=float))).iloc[-1] == 100
    assert rsi(pd.Series(np.ones(30))).iloc[-1] == 50
    assert rsi(pd.Series(-np.arange(30, dtype=float))).iloc[-1] == 0


def test_wilder_sma_seed():
    result = wilder(pd.Series([1.0, 2.0, 3.0, 8.0, 5.0]), 3)
    assert result.iloc[2] == 2
    assert result.iloc[3] == 4
    assert result.iloc[4] == pytest.approx(13 / 3)


def test_macd_independent_ema():
    close = pd.Series(np.arange(1, 70, dtype=float))
    a, b = close.iloc[0], close.iloc[0]
    lines = []
    for x in close:
        a = 2 / 13 * x + 11 / 13 * a
        b = 2 / 27 * x + 25 / 27 * b
        lines.append(a - b)
    result = macd(close)
    np.testing.assert_allclose(result.macd.iloc[25:], lines[25:])
    np.testing.assert_allclose(result.macd_hist.dropna(), (result.macd - result.macd_signal).dropna())


def test_atr_true_range_gap():
    df = pd.DataFrame({"high": [11, 13, 19, 20], "low": [9, 10, 17, 16], "close": [10, 12, 18, 19]})
    # TR = 2,3,7,4; first 3 average is 4, then Wilder(4,4)=4.
    assert atr(df, 3).iloc[2] == 4
    assert atr(df, 3).iloc[3] == 4


def test_bollinger_population_std():
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = bollinger(close, 5, 2).iloc[-1]
    assert result.bb_middle == 3
    assert result.bb_upper == pytest.approx(3 + 2 * np.sqrt(2))
    assert result.bb_lower == pytest.approx(3 - 2 * np.sqrt(2))
    assert result.bb_percent_b == pytest.approx((5 - result.bb_lower) / (result.bb_upper - result.bb_lower))


def test_indicator_gaps_restart_warmup(bars):
    data = bars.drop(bars.index[250])
    result = indicators(data)
    assert result.loc[bars.index[251], "bars_since_gap"] == 1
    assert result.loc[bars.index[251] :, "ema_200"].isna().all()


def test_all_indicators_prefix_invariant(bars):
    full, prefix = indicators(bars), indicators(bars.iloc[:260])
    pd.testing.assert_frame_equal(full.iloc[:260], prefix)
