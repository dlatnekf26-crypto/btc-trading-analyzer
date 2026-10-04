"""Confirmation delays, regime evidence, contextual scoring and higher-frame availability."""

from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from btc_analyzer.analysis.market_structure import market_structure
from btc_analyzer.analysis.multi_timeframe import prepare, enrich
from btc_analyzer.analysis.regime import regimes
from btc_analyzer.config import IndicatorConfig, AppConfig
from btc_analyzer.indicators.core import indicators
from btc_analyzer.strategy.scoring import scoring, score_label, quality_label
from btc_analyzer.strategy.signal_engine import analyze, CooldownGate
from btc_analyzer.analysis.support_resistance import zones


def test_pivot_confirmation_delay(bars):
    data = bars.iloc[:9].copy()
    data.high = [2, 3, 5, 9, 5, 3, 2, 3, 4]
    data.low = data.high - 1
    data.open = data.close = data.high - 0.5
    cfg = IndicatorConfig(pivot_left=2, pivot_right=2)
    result = market_structure(indicators(data, cfg), cfg)
    assert np.isnan(result.pivot_high.iloc[3])
    assert np.isnan(result.pivot_high.iloc[4])
    assert result.pivot_high.iloc[5] == 9
    prefix = market_structure(indicators(data.iloc[:5], cfg), cfg)
    assert prefix.pivot_high.isna().all()


def test_pivots_and_regimes_prefix_invariant(bars):
    full, prefix = enrich(bars, "1h"), enrich(bars.iloc[:270], "1h")
    pd.testing.assert_frame_equal(full.iloc[:270], prefix)


def test_higher_candle_join_uses_close(bundle):
    full = prepare(bundle, "1h")
    cutoff = full.index[-70] + pd.Timedelta(hours=1)
    short = {
        tf: df.loc[
            df.index + pd.Timedelta(seconds={"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[tf]) <= cutoff
        ]
        for tf, df in bundle.items()
    }
    prefix = prepare(short, "1h")
    pd.testing.assert_frame_equal(full.loc[prefix.index], prefix)
    frame = enrich(bundle["4h"], "4h")
    available = frame.index[-10] + pd.Timedelta(hours=4)
    earlier = full.loc[full.available_at < available].iloc[-1]
    assert earlier["close_4h"] == frame.close.iloc[-11]
    matching = full.loc[full.available_at == available].iloc[0]
    assert matching["close_4h"] == frame.close.iloc[-10]


def test_future_prices_cannot_change_past(features, bundle):
    cutoff = features.index[-40] + pd.Timedelta(hours=1)
    changed = {tf: df.copy() for tf, df in bundle.items()}
    for tf, df in changed.items():
        seconds = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[tf]
        mask = df.index + pd.Timedelta(seconds=seconds) > cutoff
        df.loc[mask, ["open", "high", "low", "close"]] *= 10
    altered = prepare(changed, "1h")
    index = features.index[features.available_at <= cutoff]
    pd.testing.assert_frame_equal(features.loc[index], altered.loc[index])


def test_strong_trend_evidence(features):
    df = features.tail(1).copy()
    df.ema_alignment = 1
    df.ema_slope = 1
    df.price_vs_ema200 = 0.1
    df.structure = "Bullish Structure"
    assert regimes(df).regime.iloc[-1] == "Strong Uptrend"
    df.ema_alignment = -1
    df.ema_slope = -1
    df.price_vs_ema200 = -0.1
    df.structure = "Bearish Structure"
    assert regimes(df).regime.iloc[-1] == "Strong Downtrend"


def test_rsi_is_never_standalone_signal(features):
    data = features.copy()
    row = data.iloc[-1].copy()
    row.rsi = 25
    row.rsi_slope = -5
    row.ema_alignment = -1
    row.ema_slope = -1
    row.price_vs_ema200 = -0.1
    row.higher_trend = -1
    row.macd_hist = -row.atr
    row.macd_hist_slope = -row.atr
    row.structure = "Bearish Structure"
    row.regime = "Strong Downtrend"
    data.iloc[-1] = row
    a = analyze(data)
    assert a.score.overall < 50
    assert not a.eligible
    row.rsi = 75
    row.rsi_slope = 5
    row.ema_alignment = 1
    row.ema_slope = 1
    row.price_vs_ema200 = 0.1
    row.higher_trend = 1
    row.macd_hist = row.atr
    row.macd_hist_slope = row.atr
    row.structure = "Bullish Structure"
    row.regime = "Strong Uptrend"
    assert scoring(row).overall > 70


@pytest.mark.parametrize(
    "value,label",
    [
        (100, "Very Strong Bullish"),
        (70, "Bullish"),
        (60, "Mild Bullish"),
        (40, "Neutral"),
        (30, "Mild Bearish"),
        (15, "Bearish"),
        (0, "Very Strong Bearish"),
    ],
)
def test_score_bands(value, label):
    assert score_label(value) == label


def test_quality_bands():
    assert [quality_label(x) for x in (49, 50, 65, 75, 85)] == [
        "No Trade",
        "Watch",
        "Weak Setup",
        "Valid Setup",
        "High Quality Setup",
    ]


def test_cooldown_requires_reset():
    gate = CooldownGate(3)
    assert gate.permit(0, True, "up")
    gate.fired(0, "up")
    assert not gate.permit(10, True, "up")
    assert not gate.permit(11, False, "up")
    assert gate.permit(12, True, "up")
    gate.fired(12, "up")
    assert not gate.permit(13, True, "new-structure")
    assert gate.permit(16, True, "new-structure")


def test_zones_bounded(features):
    levels = zones(features)
    assert len(levels) <= 6
    assert all(z.low < z.high and z.strength >= 1 for z in levels)


def test_invalid_config():
    with pytest.raises(ValueError):
        replace(AppConfig().strategy, weights={"trend": 1})
    with pytest.raises(ValueError):
        replace(AppConfig().risk, leverage=10)


def test_missing_higher_timeframes_are_not_confirmation(bundle):
    result = prepare({"1h": bundle["1h"]}, "1h")
    assert result.higher_coverage.iloc[-1] == 0
    assert result.higher_trend.iloc[-1] == 0
    assert result["trend_4h"].isna().all()
    assert result["trend_1d"].isna().all()


def test_partial_higher_coverage_has_fixed_denominator(bundle):
    result = prepare({"1h": bundle["1h"], "4h": bundle["4h"]}, "1h")
    assert result.higher_coverage.iloc[-1] == 0.5
    expected_weight = 2 / (2 + 24**0.5)
    expected = enrich(bundle["4h"], "4h").trend_direction.iloc[-1] * expected_weight
    assert result.higher_trend.iloc[-1] == pytest.approx(expected)


def test_empty_current_candles_raise_clear_error(bundle):
    with pytest.raises(ValueError, match="closed candles"):
        prepare({**bundle, "1h": bundle["1h"].iloc[:0]}, "1h")
