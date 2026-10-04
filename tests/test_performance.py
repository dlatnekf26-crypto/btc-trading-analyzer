"""Regression checks for avoided work, boundary invalidation and lazy execution."""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from btc_analyzer.candles import candle_boundary, candle_shift
from btc_analyzer.config import IndicatorConfig
from btc_analyzer.data.base_provider import normalize, DataError
from btc_analyzer.data.service import DataService, demo_bundle


def provider_frame(tf, end, *, incomplete=False):
    index = [candle_shift(end, tf, offset) for offset in (-3, -2, -1)]
    if incomplete:
        index = index[:-1]
    return normalize([[t, 100, 102, 98, 101, 100] for t in index], tf, now=end, timestamp_unit=None)


@pytest.mark.parametrize(
    "tf,end,next_end",
    [
        ("1h", "2024-02-29T12:05Z", "2024-02-29T13:00Z"),
        ("1w", "2024-02-29T12:05Z", "2024-03-04T00:00Z"),
        ("1M", "2024-02-29T12:05Z", "2024-03-01T00:00Z"),
    ],
)
def test_closed_history_reused_between_refreshes_but_new_boundary_invalidates(
    tmp_path, monkeypatch, tf, end, next_end
):
    calls = []

    class Provider:
        def fetch(self, symbol, timeframe, start, stop):
            calls.append(stop)
            return provider_frame(timeframe, stop)

    monkeypatch.setattr("btc_analyzer.data.service.BinanceProvider", Provider)
    service = DataService(tmp_path / "cache.sqlite", ttl=1)
    start = pd.Timestamp("2020-01-01T00:00Z")
    end = pd.Timestamp(end)
    first = service.fetch("Binance", "BTC/USDT", tf, start, end)
    repeated = service.fetch("Binance", "BTC/USDT", tf, start, end + pd.Timedelta(minutes=3))
    pd.testing.assert_frame_equal(first, repeated)
    assert len(calls) == 1 and repeated.attrs["cached"]
    service.fetch("Binance", "BTC/USDT", tf, start, pd.Timestamp(next_end))
    assert len(calls) == 2
    service.fetch("Binance", "BTC/USDT", tf, start, pd.Timestamp(next_end), refresh=True)
    assert len(calls) == 3


def test_incomplete_boundary_is_not_persisted_as_fresh(tmp_path, monkeypatch):
    calls = []

    class Provider:
        def fetch(self, symbol, tf, start, end):
            calls.append(end)
            return provider_frame(tf, end, incomplete=len(calls) == 1)

    monkeypatch.setattr("btc_analyzer.data.service.BinanceProvider", Provider)
    service = DataService(tmp_path / "lag.sqlite")
    args = ("Binance", "BTC/USDT", "1h", "2024-01-01", "2024-02-01T12:05Z")
    first, second = service.fetch(*args), service.fetch(*args)
    assert len(first) == 2 and len(second) == 3 and len(calls) == 2
    service.fetch(*args)
    assert len(calls) == 2


def test_one_provider_per_bundle_and_long_history_cache_reused(tmp_path, monkeypatch):
    instances, calls = [], []
    clock = [1000.0]

    class Provider:
        def __init__(self):
            instances.append(self)

        def fetch(self, symbol, tf, start, end):
            calls.append(tf)
            return provider_frame(tf, end)

    monkeypatch.setattr("btc_analyzer.data.service.BinanceProvider", Provider)
    monkeypatch.setattr("btc_analyzer.data.service.time.time", lambda: clock[0])
    args = ("Binance", "BTC/USDT", "1d", pd.Timestamp("2024-01-01T00:00Z"), pd.Timestamp("2024-02-29T12:05Z"))
    path = tmp_path / "cache.sqlite"
    DataService(path).bundle(*args, include_macro=True)
    assert len(instances) == 1 and set(calls) == {"1h", "4h", "1d", "1w", "1M"}
    clock[0] += 600
    DataService(path).bundle(*args[:-1], args[-1] + pd.Timedelta(minutes=3), include_macro=True)
    assert len(instances) == 1 and len(calls) == 5


def test_feature_cache_reuses_work_and_invalidates_price_and_config(bars, monkeypatch):
    from btc_analyzer.ui import analysis_cache

    original = analysis_cache.enrich
    calls = []

    def enriched(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(analysis_cache, "enrich", enriched)
    analysis_cache.feature_frame.clear()
    first = analysis_cache.feature_frame(bars, "1h", IndicatorConfig())
    first.iloc[-1, 0] = 0
    second = analysis_cache.feature_frame(bars, "1h", IndicatorConfig())
    assert second.iloc[-1, 0] != 0 and len(calls) == 1
    changed = bars.copy()
    changed.iloc[-1, 3] += 0.1
    analysis_cache.feature_frame(changed, "1h", IndicatorConfig())
    analysis_cache.feature_frame(changed, "1h", IndicatorConfig(rsi_length=16))
    assert len(calls) == 3
    analysis_cache.feature_frame.clear()


def test_ui_only_runs_active_tab_and_live_refresh_reuses_data(monkeypatch, tmp_path):
    import streamlit as st
    from btc_analyzer.ui import analysis_cache

    st.cache_data.clear()
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "dashboard.sqlite"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "live")
    monkeypatch.setenv("BTC_DEFAULT_EXCHANGE", "Binance")
    calls = {"bundle": 0, "quote": 0, "features": 0}

    def bundle(self, exchange, symbol, tf, start, end, **kwargs):
        calls["bundle"] += 1
        return demo_bundle(tf, 400, end=end, include_macro=True)

    def quote(self, symbol):
        calls["quote"] += 1
        raise DataError("Ticker temporarily unavailable")

    original = analysis_cache.enrich

    def enriched(*args, **kwargs):
        calls["features"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(DataService, "bundle", bundle)
    monkeypatch.setattr("btc_analyzer.data.binance_provider.BinanceProvider.quote", quote)
    monkeypatch.setattr(analysis_cache, "enrich", enriched)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=45).run()
    assert not app.exception and not app.error
    assert len(app.get("plotly_chart")) == 1 and len(app.dataframe) <= 1
    assert calls == {"bundle": 1, "quote": 1, "features": 5}
    next(x for x in app.get("button_group") if x.label == "차트 보기").set_value("상세").run()
    assert calls == {"bundle": 1, "quote": 1, "features": 5}
    app.session_state["dashboard_tab"] = "다중 시간대"
    app.run()
    assert len(app.get("plotly_chart")) == 0 and len(app.dataframe) == 3
    assert calls == {"bundle": 1, "quote": 1, "features": 5}
    next(x for x in app.button if x.label == "데이터 새로고침").click().run()
    assert calls["bundle"] == 2 and calls["quote"] == 2
    app.run()
    assert calls["bundle"] == 3 and calls["quote"] == 2  # refill memory from persistent cache once
    app.run()
    assert calls["bundle"] == 3 and not app.exception and not app.error
    st.cache_data.clear()


def test_calendar_cache_boundary_uses_monday_and_real_leap_month():
    assert candle_boundary(pd.Timestamp("2024-02-29T23:59Z"), "1M") == pd.Timestamp("2024-02-01T00:00Z")
    assert candle_boundary(pd.Timestamp("2024-02-29T23:59Z"), "1w") == pd.Timestamp("2024-02-26T00:00Z")
