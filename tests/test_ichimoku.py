"""Independent Ichimoku windows and no future leakage through display shifts."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.multi_timeframe import enrich
from btc_analyzer.candles import candle_shift
from btc_analyzer.config import AppConfig, IndicatorConfig
from btc_analyzer.indicators.core import ichimoku, indicators
from btc_analyzer.strategy.scoring import scoring
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.ui.charts import price_chart
from btc_analyzer.ui.presentation import ichimoku_cards


def test_ichimoku_matches_independent_midpoints_and_shift():
    x = np.arange(120, dtype=float)
    df = pd.DataFrame({"high": x + 12, "low": x + 8, "close": x + 10})
    result = ichimoku(df)
    row = result.iloc[90]
    assert row.ichimoku_tenkan == 96
    assert row.ichimoku_kijun == 87.5
    assert row.ichimoku_span_a == 91.75
    assert row.ichimoku_span_b == 74.5
    assert row.ichimoku_cloud_a == 65.75
    assert row.ichimoku_cloud_b == 48.5
    assert row.ichimoku_chikou_reference == 74
    assert row.ichimoku_cloud_position == 1
    assert row.ichimoku_bias == pytest.approx(1)
    assert result.ichimoku_cloud_b.iloc[:77].isna().all()
    assert pd.notna(result.ichimoku_cloud_b.iloc[77])


def test_chikou_signal_rows_cannot_read_later_close(bars):
    before = ichimoku(bars)
    changed = bars.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 100
    after = ichimoku(changed)
    pd.testing.assert_frame_equal(before.iloc[:-1], after.iloc[:-1])
    assert after.ichimoku_chikou_reference.iloc[-1] == bars.close.iloc[-27]
    assert "ichimoku_chikou" not in before.columns


def test_ichimoku_gaps_require_new_cloud_history(bars):
    data = bars.drop(bars.index[220])
    features = indicators(data)
    assert features.loc[bars.index[221], "bars_since_gap"] == 1
    assert features.loc[bars.index[221] : bars.index[297], "ichimoku_cloud_b"].isna().all()
    assert pd.notna(features.loc[bars.index[298], "ichimoku_cloud_b"])


def test_custom_ichimoku_periods_are_serialized_and_validated(bars):
    custom = replace(
        IndicatorConfig(),
        ichimoku_conversion=7,
        ichimoku_base=22,
        ichimoku_span_b=44,
        ichimoku_displacement=22,
    )
    config = AppConfig(indicators=custom)
    restored = AppConfig.from_dict(config.to_dict())
    assert restored.indicators == custom
    features = indicators(bars, custom)
    assert features.attrs["ichimoku_displacement"] == 22
    assert features.ichimoku_cloud_b.iloc[:65].isna().all()
    assert pd.notna(features.ichimoku_cloud_b.iloc[65])
    with pytest.raises(ValueError, match="Ichimoku"):
        replace(custom, ichimoku_conversion=50)
    with pytest.raises(ValueError):
        replace(custom, ichimoku_displacement=0)


def test_ichimoku_changes_contextual_trend_score(features):
    row = features.iloc[-1].copy()
    row.ichimoku_bias = -1
    lower = scoring(row).categories["trend"]
    row.ichimoku_bias = 1
    higher = scoring(row).categories["trend"]
    assert higher > lower
    assert higher - lower == pytest.approx(15)


def test_monthly_cloud_projection_is_calendar_geometry_only(bars):
    monthly = bars.tail(100).copy()
    monthly.index = pd.date_range("2017-09-01", periods=100, freq="MS", tz="UTC", name="timestamp")
    features = enrich(monthly, "1M")
    features.attrs["timeframe"] = "1M"
    figure = price_chart(
        features,
        analyze(features),
        averages=(),
        bands=False,
        ichimoku=True,
        zones_visible=False,
        levels_visible=False,
        bars=60,
    )
    candle = next(trace for trace in figure.data if trace.type == "candlestick")
    assert len(candle.x) == 60
    assert pd.Timestamp(candle.x[-1]).tz_convert("UTC") == features.index[-1]
    cloud = [trace for trace in figure.data if trace.legendgroup == "ichimoku-cloud"]
    assert cloud
    plotted_end = max(pd.Timestamp(t).tz_convert("UTC") for trace in cloud for t in trace.x)
    assert plotted_end == candle_shift(features.index[-1], "1M", 26)
    assert all(pd.Timestamp(t).day == 1 for trace in cloud for t in trace.x)
    lag = next(trace for trace in figure.data if trace.name == "후행스팬")
    assert pd.Timestamp(lag.x[-1]).tz_convert("UTC") == candle_shift(features.index[-1], "1M", -26)
    assert lag.y[-1] == features.close.iloc[-1]
    assert {trace.name for trace in figure.data}.issuperset({"전환선", "기준선", "후행스팬"})


def test_simple_chart_has_cloud_and_detail_can_hide_overlays(features):
    analysis = analyze(features)
    simple = price_chart(
        features,
        analysis,
        averages=(),
        bands=False,
        ichimoku=True,
        ichimoku_detail=False,
        zones_visible=False,
        levels_visible=False,
    )
    assert any(trace.legendgroup == "ichimoku-cloud" for trace in simple.data)
    assert not {trace.name for trace in simple.data}.intersection({"전환선", "기준선", "후행스팬"})
    bare = price_chart(
        features,
        analysis,
        averages=(),
        bands=False,
        ichimoku=False,
        zones_visible=False,
        levels_visible=False,
    )
    assert {trace.name for trace in bare.data} == {"가격", "거래량"}
    assert not bare.layout.shapes


def test_missing_ichimoku_values_are_explained():
    result = ichimoku_cards({"ichimoku_cloud_position": None, "ichimoku_tk_direction": float("nan")})
    assert result.count("이력 부족") == 3
    assert "구름 위</strong>" not in result
