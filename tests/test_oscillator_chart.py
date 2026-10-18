"""Shared oscillator time axes, exact values, gap handling and unchanged markup."""

from base64 import b64decode

import numpy as np
import pytest

from btc_analyzer.data.service import demo_bundle
from btc_analyzer.indicators.core import indicators
from btc_analyzer.ui.market_view import market_chart_spec
from btc_analyzer.ui.chart_reader import reader_html


def numbers(data):
    return (
        np.frombuffer(b64decode(data["bdata"]), dtype=data["dtype"])
        if isinstance(data, dict)
        else np.asarray(data)
    )


@pytest.mark.parametrize("tf", ["5m", "15m", "1h", "4h", "1d", "1w", "1M"])
def test_panels_reuse_exact_closed_features_and_all_time_axes(tf):
    raw = demo_bundle(tf, bars=300, end="2026-10-01T00:00Z")[tf]
    features = indicators(raw, timeframe=tf)
    spec = market_chart_spec(features, "Asia/Seoul", ("ema_20",), True, "USDT", True, True, 150, tf, 26)
    meta = spec["layout"]["meta"]["btcLive"]
    expected = features.tail(150)
    axes = {"rsi": "y3", "macd": "y4", "macd_signal": "y4", "macd_hist": "y4"}
    for index, field in meta["overlays"].items():
        if field not in axes:
            continue
        trace = spec["data"][int(index)]
        assert trace["x"] == spec["data"][0]["x"]
        assert trace["yaxis"] == axes[field]
        np.testing.assert_allclose(numbers(trace["y"]), expected[field], equal_nan=True)
    assert set(axes).issubset(meta["overlays"].values())
    assert list(spec["layout"]["yaxis3"]["range"]) == [0, 100]
    assert spec["layout"]["yaxis4"]["range"][0] < 0 < spec["layout"]["yaxis4"]["range"][1]
    assert all(spec["layout"][key]["type"] == "date" for key in ("xaxis", "xaxis2", "xaxis3", "xaxis4"))
    assert spec["data"][meta["volumeIndex"]]["name"] == "거래량"


def test_missing_contiguous_history_does_not_invent_rsi_or_macd():
    raw = demo_bundle("1h", bars=240, end="2026-10-01T00:00Z")["1h"]
    features = indicators(raw.drop(raw.index[-5]), timeframe="1h")
    spec = market_chart_spec(features, "Asia/Seoul", (), False, "USDT", False, False, 100, "1h", 26)
    for index, field in spec["layout"]["meta"]["btcLive"]["overlays"].items():
        if field in ("rsi", "macd", "macd_signal", "macd_hist"):
            assert np.isnan(numbers(spec["data"][int(index)]["y"])[-1])
    html = reader_html(features, "1h", "XRP", (), False)
    assert 'data-field="rsi">—' in html and 'data-field="macd_signal">—' in html
    features.loc[features.index[-1], "macd_hist"] = 0.00000023
    assert 'data-field="macd_hist">0.00000023' in reader_html(features, "1h", "XRP", (), False)
