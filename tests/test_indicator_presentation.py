"""Indicator explanations must respect units, warmup and distinct MACD signals."""

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.config import IndicatorConfig
from btc_analyzer.ui.charts import indicator_chart
from btc_analyzer.ui.indicators_view import indicator_cards


def cards(**values):
    return indicator_cards(pd.DataFrame([values]), IndicatorConfig())


@pytest.mark.parametrize(
    "value, state",
    [
        (0, "매도 과열 구간"),
        (30, "매도 과열 구간"),
        (49, "매도 힘 우위"),
        (50, "힘의 균형"),
        (49.96, "힘의 균형"),
        (50.04, "힘의 균형"),
        (51, "매수 힘 우위"),
        (70, "매수 과열 구간"),
        (100, "매수 과열 구간"),
    ],
)
def test_rsi_boundaries_describe_strength_without_reversal_claim(value, state):
    card = cards(rsi=value)[1]
    assert card.state == state
    assert "반전 확정은 아니" in card.meaning


@pytest.mark.parametrize("value", [np.nan, np.inf, -1, 101, None])
def test_invalid_rsi_is_not_a_market_state(value):
    assert cards(rsi=value)[1].state == "자료 부족"


def test_macd_below_zero_can_still_be_above_signal():
    card = cards(macd=-5, macd_signal=-7)[2]
    assert card.state == "기준선 위" and card.value == "+2.00 USDT"
    assert "0 아래" in card.meaning
    card = cards(macd=5, macd_signal=7)[2]
    assert card.state == "기준선 아래" and "0 위" in card.meaning
    assert "0과 같아요" in cards(macd=0, macd_signal=0)[2].meaning


def test_latest_missing_row_does_not_reuse_old_valid_state():
    old = {
        "ema_20": 20,
        "ema_50": 10,
        "rsi": 75,
        "macd": 2,
        "macd_signal": 1,
        "atr_pct": 2,
        "volume_ratio": 2,
        "close": 10,
        "ichimoku_cloud_a": 8,
        "ichimoku_cloud_b": 9,
    }
    frame = pd.DataFrame([old, {key: np.nan for key in old}])
    assert all(card.state == "자료 부족" for card in indicator_cards(frame, IndicatorConfig()))
    assert all(card.state == "자료 부족" for card in indicator_cards(pd.DataFrame(), IndicatorConfig()))


def test_cloud_uses_current_shifted_cloud_not_projected_values():
    values = dict(
        close=100, ichimoku_cloud_a=90, ichimoku_cloud_b=110, ichimoku_span_a=50, ichimoku_span_b=60
    )
    assert cards(**values)[5].state == "구름 안"
    assert cards(**{**values, "close": 120})[5].state == "구름 위"
    assert cards(**{**values, "close": 80})[5].state == "구름 아래"
    assert cards(**{**values, "ichimoku_cloud_a": np.nan})[5].state == "자료 부족"


def test_atr_relative_state_requires_reference_and_volume_is_directionless():
    frame = pd.DataFrame({"atr_pct": [2.0] * 19 + [3.0]})
    card = indicator_cards(frame, IndicatorConfig())[3]
    assert card.state == "평소보다 큼" and card.value == "3.00%"
    assert "20봉 중앙값" in card.meaning
    assert cards(atr_pct=3)[3].state == "변동 폭 확인"
    assert "방향을 정하지" in cards(volume_ratio=2)[4].meaning


@pytest.mark.parametrize(
    "kind, count, unit",
    [("RSI", 1, "점"), ("MACD", 3, "USDT"), ("ATR", 1, "%"), ("BB", 1, "%"), ("VOLUME", 1, "배")],
)
def test_focused_charts_preserve_numbers_units_and_touch_axes(features, kind, count, unit):
    frame = features
    fig = indicator_chart(frame, kind=kind)
    assert len(fig.data) == count
    assert all(len(trace.x) <= 120 for trace in fig.data)
    assert all(unit in trace.hovertemplate for trace in fig.data)
    assert fig.layout.dragmode is False
    assert fig.layout.xaxis.fixedrange and fig.layout.yaxis.fixedrange
    if kind == "BB":
        np.testing.assert_allclose(fig.data[0].y, frame.bb_width.tail(120) * 100, equal_nan=True)
        assert "중심선" in fig.layout.yaxis.title.text
    if kind == "RSI":
        assert tuple(fig.layout.yaxis.range) == (0, 100)
