"""Actual chart comparison UI, bounded API paging and cache/error behavior."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from btc_analyzer.analysis.historical_similarity import HISTORY_BARS, find_similar_history
from btc_analyzer.candles import candle_boundary, candle_close, history_start
from btc_analyzer.data.base_provider import DataError, normalize
from btc_analyzer.data.binance_provider import BinanceProvider
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.ui import history_view

ROOT = Path(__file__).resolve().parents[1]


def flat_history(tf, end, count=3000):
    freq = {"1h": "h", "4h": "4h", "1d": "D", "1w": "W-MON", "1M": "MS"}[tf]
    index = pd.date_range(end=end, periods=count + 1, freq=freq)[:-1]
    return normalize([[t, 100, 102, 98, 100, 100] for t in index], tf, now=end, timestamp_unit=None)


def choose_history(app):
    app.session_state["dashboard_tab"] = "미래 예측"
    return app.run(timeout=45)


@pytest.mark.parametrize("tf", ["1d", "1w", "1M"])
def test_history_automatically_pages_the_bounded_same_exchange_and_reuses_closed_cache(
    tmp_path, monkeypatch, tf
):
    end = candle_boundary(pd.Timestamp("2026-10-05T12:05Z"), tf)
    calls = []

    class Client:
        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            calls.append((symbol, timeframe, since, limit))
            assert symbol == "BTC/USDT" and timeframe == tf and limit == 1000
            freq = {"1d": "D", "1w": "W-MON", "1M": "MS"}[timeframe]
            index = pd.date_range(pd.Timestamp(since, unit="ms", tz="UTC"), periods=limit, freq=freq)
            return [[int(t.timestamp() * 1000), 100, 102, 98, 100, 100] for t in index]

    monkeypatch.setattr("btc_analyzer.data.service.BinanceProvider", lambda: BinanceProvider(Client()))
    args = (str(tmp_path / "market.sqlite"), "Binance", "BTC/USDT", tf, end.isoformat())
    first = history_view.fetch_history(*args)["frame"]
    expected_start = max(history_start(end, tf, HISTORY_BARS[tf]), pd.Timestamp("2017-08-01T00:00Z"))
    assert calls[0][2] == int(expected_start.timestamp() * 1000)
    assert len(first) <= HISTORY_BARS[tf] and candle_close(first.index[-1], tf) == end
    assert len(calls) == (3 if tf == "1d" else 1)
    second = history_view.fetch_history(*args)["frame"]
    assert second.attrs["cached"] and len(calls) == (3 if tf == "1d" else 1)
    pd.testing.assert_frame_equal(first, second)


def test_live_tab_collects_only_when_open_and_controls_and_refresh_reuse_work(
    monkeypatch, tmp_path, offline_dashboard
):
    st.cache_data.clear()
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "live")
    monkeypatch.setenv("BTC_DEFAULT_EXCHANGE", "Binance")
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    calls = []

    monkeypatch.setattr(
        DataService,
        "bundle",
        lambda self, exchange, symbol, tf, start, end, **kwargs: demo_bundle(
            tf, 400, end=end, include_macro=True
        ),
    )
    monkeypatch.setattr(
        BinanceProvider,
        "quote",
        lambda self, symbol: {
            "price": 90000,
            "change_24h": 0,
            "observed_at": pd.Timestamp.now(tz="UTC").isoformat(),
        },
    )

    def fetched(self, exchange, symbol, tf, start, end, **kwargs):
        calls.append((self.path, exchange, symbol, tf, kwargs.get("refresh")))
        return flat_history(tf, end)

    monkeypatch.setattr(DataService, "fetch", fetched)
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=45).run()
    assert not app.exception and not app.error and not calls
    decision = next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value)
    choose_history(app)
    assert not app.exception and not app.error
    assert len(calls) == 1 and calls[0][1:4] == ("Binance", "BTC/USDT", "1d")
    assert calls[0][0] == tmp_path / "web/market-cache.sqlite3"
    assert any("Binance 공개 시세 API" in x.value for x in app.caption)
    assert any('aria-label="예측 요약"' in x.value for x in app.markdown)
    assert len(app.get("plotly_chart")) == 1
    next(item for item in app.get("button_group") if item.label == "예측 기간").set_value("6mo")
    choose_history(app)
    assert len(calls) == 1
    next(item for item in app.button if item.label == "비교 자료 새로고침").click()
    choose_history(app)
    assert len(calls) == 2 and calls[-1][-1] is True
    choose_history(app)
    assert len(calls) == 2
    assert next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value) == decision
    next(item for item in app.get("button_group") if item.label == "예측 기간").set_value("custom")
    choose_history(app)
    next(item for item in app.get("button_group") if item.label == "비교 시간대").set_value("1w")
    choose_history(app)
    assert len(calls) == 3 and calls[-1][3] == "1w"
    assert not app.exception and not app.error
    st.cache_data.clear()


def test_live_history_failure_is_cached_and_never_replaced_with_demo(
    monkeypatch, tmp_path, offline_dashboard
):
    st.cache_data.clear()
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "live")
    monkeypatch.setenv("BTC_DEFAULT_EXCHANGE", "Binance")
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setattr(
        DataService,
        "bundle",
        lambda self, exchange, symbol, tf, start, end, **kwargs: demo_bundle(
            tf, 400, end=end, include_macro=True
        ),
    )
    monkeypatch.setattr(
        BinanceProvider,
        "quote",
        lambda self, symbol: {
            "price": 90000,
            "change_24h": 0,
            "observed_at": pd.Timestamp.now(tz="UTC").isoformat(),
        },
    )
    calls = []

    def failure(*args, **kwargs):
        calls.append(1)
        raise DataError("HTTP 451: Market data unavailable")

    monkeypatch.setattr(DataService, "fetch", failure)
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=45).run()
    choose_history(app)
    assert not app.exception and len(calls) == 1
    assert any("과거 비교 자료" in item.value and "451" in item.value for item in app.error)
    assert not app.get("plotly_chart") and not any("가장 닮은 과거" in x.value for x in app.success)
    choose_history(app)
    assert len(calls) == 1
    next(item for item in app.button if item.label == "비교 자료 새로고침").click()
    choose_history(app)
    choose_history(app)
    assert len(calls) == 2
    assert not any("DEMO" in item.value for item in app.warning)
    st.cache_data.clear()


def test_live_comparison_uses_public_history_and_five_timeframes(monkeypatch, tmp_path, offline_dashboard):
    st.cache_data.clear()
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    app = AppTest.from_file(ROOT / "app.py", default_timeout=45).run()
    next(item for item in app.get("button_group") if item.label == "차트 시간대").set_value("4h").run()
    next(item for item in app.button if item.label == "예측과 과거 차트 함께 보기").click()
    choose_history(app)
    assert app.session_state["similarity_timeframe"] == "4h"
    assert not app.exception and not app.error
    for tf in ("1h", "4h", "1d", "1w", "1M"):
        next(item for item in app.get("button_group") if item.label == "비교 시간대").set_value(tf)
        choose_history(app)
        assert not app.exception and not app.error
        assert not any("DEMO" in item.value or "합성" in item.value for item in app.warning)
        assert any("Binance 공개 시세 API" in item.value for item in app.caption)
    st.cache_data.clear()


def test_calculation_cache_invalidates_actual_price_changes_without_changing_other_visitors():
    history_view.history_comparison.clear()
    end = pd.Timestamp("2024-01-01T00:00Z")
    original = flat_history("1d", end, 300)
    first = history_view.history_comparison(original, "1d", end.isoformat(), 30, 30, 60)
    changed = original.copy()
    changed.iloc[-10:, :4] *= np.linspace(1, 1.2, 10)[:, None]
    second = history_view.history_comparison(changed, "1d", end.isoformat(), 30, 30, 60)
    assert first.current_path != second.current_path
    assert history_view.history_comparison(original, "1d", end.isoformat(), 30, 30, 60) == first
    assert second == find_similar_history(changed, "1d", end, 30, 30)
    history_view.history_comparison.clear()


def test_removed_forecast_footers_never_build_tables_or_downloads_and_keep_decision(
    monkeypatch, tmp_path, offline_dashboard
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Removed forecast tables and downloads must never execute")

    monkeypatch.setattr(st, "download_button", forbidden)
    monkeypatch.setattr(st, "dataframe", forbidden)
    st.cache_data.clear()
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    app = AppTest.from_file(ROOT / "app.py", default_timeout=45).run()
    decision = next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value)
    next(item for item in app.button if item.label == "미래 예측 보기 →").click()
    choose_history(app)
    assert not app.exception and not app.error
    assert any('aria-label="예측 요약"' in item.value for item in app.markdown)
    assert len(app.get("plotly_chart")) == 1
    assert not app.get("dataframe") and not app.get("download_button")
    app.session_state["forecast_validation_details"] = True
    app.session_state["history_downloads"] = True
    choose_history(app)
    assert not app.exception and not app.error
    assert not app.metric and not app.get("dataframe") and not app.get("download_button")
    assert not any("과거 예측 성적" in item.label or "세부 유사도" in item.label for item in app.expander)
    assert next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value) == decision
    next(item for item in app.get("button_group") if item.label == "분석 보기").set_value("과거 비교")
    choose_history(app)
    assert any("예측선이 아닙니다" in item.value for item in app.caption)
    assert not app.exception and len(app.get("plotly_chart")) == 1
    st.cache_data.clear()


def test_forecast_cache_tracks_price_changes_and_returned_forecasts_are_isolated():
    history_view.forecast_analysis.clear()
    end = pd.Timestamp("2024-01-01T00:00Z")
    original = flat_history("1d", end, 1000)
    first = history_view.forecast_analysis(original, "1d", end.isoformat(), 30, 30, 60)
    changed = original.copy()
    changed.iloc[-1, :4] *= 1.01
    second = history_view.forecast_analysis(changed, "1d", end.isoformat(), 30, 30, 60)
    assert first.history.anchor_price != second.history.anchor_price
    assert first.prediction is not None and second.prediction is not None
    assert first.prediction.center[0] != second.prediction.center[0]
    assert history_view.forecast_analysis(original, "1d", end.isoformat(), 30, 30, 60) == first
    history_view.forecast_analysis.clear()


def test_quick_horizons_have_exact_end_dates_and_a_focused_case_comparison(
    monkeypatch, tmp_path, offline_dashboard
):
    import json
    from btc_analyzer.analysis.forecast import horizon_days

    st.cache_data.clear()
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "quick.sqlite"))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=45).run()
    choose_history(app)
    origin = pd.Timestamp.now(tz="UTC").normalize().tz_convert("Asia/Seoul").tz_localize(None)
    for horizon in ("1w", "1mo", "6mo", "3mo"):
        next(item for item in app.get("button_group") if item.label == "예측 기간").set_value(horizon)
        choose_history(app)
        assert not app.exception and not app.error
        chart = json.loads(app.get("plotly_chart")[0].proto.spec)
        expected_days = horizon_days(origin.tz_localize("Asia/Seoul").tz_convert("UTC"), horizon)
        assert len(chart["data"][3]["x"]) == expected_days + 1
        assert pd.Timestamp(chart["data"][3]["x"][-1]) == origin + pd.Timedelta(days=expected_days)
        assert any("일봉" in item.value and "자료:" in item.value for item in app.caption)

    def unexpected_forecast(*args, **kwargs):
        raise AssertionError("Past comparison must not run forecast validation")

    monkeypatch.setattr(history_view, "forecast_analysis", unexpected_forecast)
    next(item for item in app.get("button_group") if item.label == "분석 보기").set_value("과거 비교")
    choose_history(app)
    fig = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(fig["data"]) == 3
    assert fig["data"][0]["y"][-1] == fig["data"][2]["y"][-1] == 0
    assert fig["data"][1]["y"][0] == 0
    assert fig["data"][0]["xaxis"] != fig["data"][1]["xaxis"]
    next(item for item in app.selectbox if item.label == "비슷했던 시기").set_value(1)
    choose_history(app)
    assert not app.exception
    assert any('aria-label="선택한 과거 요약"' in item.value for item in app.markdown)
    assert not app.get("dataframe")  # No hidden all-cases table in the default comparison.
    next(item for item in app.toggle if item.label == "모든 사례 겹쳐보기").set_value(True)
    choose_history(app)
    assert len(json.loads(app.get("plotly_chart")[0].proto.spec)["data"]) > 3
    st.cache_data.clear()


def test_previous_year_selection_migrates_to_three_months(monkeypatch, tmp_path, offline_dashboard):
    st.cache_data.clear()
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "migrate.sqlite"))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=45)
    app.session_state["dashboard_tab"] = "미래 예측"
    app.session_state["forecast_horizon"] = "1y"
    app.run()
    assert not app.exception and not app.error
    control = next(item for item in app.get("button_group") if item.label == "예측 기간")
    assert control.value == "3mo"
    target = pd.Timestamp.now(tz="UTC").normalize() + pd.DateOffset(months=3)
    assert any(f"예측 도착일 {target:%Y.%m.%d}" in item.value for item in app.caption)
    st.cache_data.clear()
