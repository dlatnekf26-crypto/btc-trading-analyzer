"""KOSPI source identity, KRX sessions, gaps and the complete shared analysis UI."""

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.forecast import forecast_dates
from btc_analyzer.data.exchange_history import aggregate, calendar_bars, horizon_bars, parse_history
from btc_analyzer.data.market_context import parse_quote
from btc_analyzer.indicators.core import indicators
from btc_analyzer.market_clock import bar_closes, gap_groups, shift_bars

NOW = pd.Timestamp("2026-10-18T12:00Z")


def payload(tf="1d", count=400):
    starts, ends = calendar_bars(2024, 2027, tf, "KOSPI")
    index = starts[ends <= NOW][-count:]
    x = np.arange(len(index))
    price = 2800 + 150 * np.sin(x / 25) + x * 0.2
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "^KS11",
                        "currency": "KRW",
                        "instrumentType": "INDEX",
                        "exchangeTimezoneName": "Asia/Seoul",
                        "dataGranularity": tf,
                        "regularMarketPrice": 2800,
                        "regularMarketTime": int(NOW.timestamp()) - 60,
                    },
                    "timestamp": (index.asi8 // 1_000_000_000).tolist(),
                    "indicators": {
                        "quote": [
                            {
                                "open": price.tolist(),
                                "high": (price + 5).tolist(),
                                "low": (price - 5).tolist(),
                                "close": price.tolist(),
                                "volume": [1000] * len(index),
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_korean_holidays_are_continuous_but_missing_trading_day_resets_indicators():
    frame = parse_history(payload(), "1d", NOW, "KOSPI")
    assert len(set(gap_groups(frame, "1d"))) == 1
    feature = indicators(frame, timeframe="1d")
    assert feature.bars_since_gap.iloc[-1] == 400 and pd.notna(feature.ema_200.iloc[-1])
    assert bar_closes(frame, frame.index[-1], "1d") == pd.Timestamp("2026-10-16T06:30Z")
    assert pd.Timestamp("2026-10-09T00:00Z") not in frame.index  # Hangul Day, US market open.
    missing = frame.drop(frame.index[-5])
    broken = indicators(missing, timeframe="1d")
    assert broken.bars_since_gap.iloc[-1] == 4 and pd.isna(broken.ema_20.iloc[-1])
    dates = forecast_dates(pd.Timestamp("2026-10-08T06:30Z"), "1d", 3, "KOSPI")
    assert dates == tuple(pd.to_datetime(["2026-10-08T06:30Z", "2026-10-12T06:30Z", "2026-10-13T06:30Z"]))
    assert horizon_bars(pd.Timestamp("2026-10-08T06:30Z"), "1w", "KOSPI") == 4


@pytest.mark.parametrize("tf", ["5m", "15m", "1h", "4h", "1d"])
def test_special_krx_hours_and_weekend_cloud_use_real_sessions(tf):
    starts, ends = calendar_bars("2026-11-19", "2026-11-19", tf, "KOSPI")
    assert starts[0] == pd.Timestamp("2026-11-19T00:00Z" if tf == "1d" else "2026-11-19T01:00Z")
    assert ends[-1] == pd.Timestamp("2026-11-19T07:30Z")
    starts, ends = calendar_bars("2026-01-02", "2026-01-02", tf, "KOSPI")
    assert ends[-1] == pd.Timestamp("2026-01-02T06:30Z")
    if tf != "1d":
        assert starts[0] == pd.Timestamp("2026-01-02T01:00Z")
    frame = parse_history(payload("15m", 600), "15m", NOW, "KOSPI")
    shifted = shift_bars(frame, frame.index[-1:], "15m", 26)
    assert shifted[0] == pd.Timestamp("2026-10-19T06:15Z")


def test_aggregate_is_session_anchored_and_withholds_missing_or_unclosed_bars():
    hourly = parse_history(payload("1h"), "1h", NOW, "KOSPI")
    four = aggregate(hourly, "4h", NOW)
    assert set(four.index.hour) == {0, 4}
    assert four.index[-1] not in aggregate(hourly.drop(hourly.index[-2]), "4h", NOW).index
    daily = parse_history(payload(), "1d", NOW, "KOSPI")
    weekly = aggregate(daily, "1w", NOW)
    assert weekly.index[-1] not in aggregate(daily.drop(daily.index[-3]), "1w", NOW).index
    assert not (bar_closes(weekly, weekly.index, "1w") > NOW).any()
    early = parse_history(payload(), "1d", pd.Timestamp("2026-10-16T06:29Z"), "KOSPI")
    assert early.index[-1] == pd.Timestamp("2026-10-15T00:00Z")


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "^KQ11"),
        ("currency", "USD"),
        ("exchangeTimezoneName", "America/New_York"),
        ("dataGranularity", "1wk"),
    ],
)
def test_wrong_index_units_timezone_or_interval_never_enters_analysis(field, value):
    data = payload()
    data["chart"]["result"][0]["meta"][field] = value
    with pytest.raises(ValueError):
        parse_history(data, "1d", NOW, "KOSPI")


def test_current_quote_requires_krw_cash_index_and_korean_timezone():
    data = payload()
    assert parse_quote(data, "^KS11", NOW.to_pydatetime()).price == 2800
    for field, value in [
        ("symbol", "NQ=F"),
        ("currency", "USD"),
        ("instrumentType", "FUTURE"),
        ("exchangeTimezoneName", "UTC"),
    ]:
        data = payload()
        data["chart"]["result"][0]["meta"][field] = value
        with pytest.raises(ValueError):
            parse_quote(data, "^KS11", NOW.to_pydatetime())


def test_kospi_full_chart_forecast_and_market_switch_isolation(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from offline_ui_fixture import offline_market_data

    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path))
    with offline_market_data(root):
        app = AppTest.from_file(root / "web_app.py", default_timeout=60).run()
        next(x for x in app.get("button_group") if x.label == "분석할 시장").set_value("KOSPI").run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        assert spec["layout"]["meta"]["btcLive"]["symbol"] == "^KS11"
        assert any("KRX 코스피 종합지수" in x.value for x in app.caption)
        assert not app.get("btc-live-analysis")
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        meta = spec["layout"]["meta"]["btcLive"]
        assert meta["symbol"] == "^KS11" and len(meta["indicatorOverlays"]) == 6
        assert meta["liveIndices"] == [] and not any("실시간" in t["name"] for t in spec["data"])
        assert next(x for x in app.toggle if x.label == "뉴스 영향 함께 반영").disabled
        assert not any("새 코인 뉴스" in x.value for x in app.caption)
        release = next(x for x in app.get("button_group") if x.label == "발표 결과를 가정해 보기")
        assert release.options == ["예상 부합", "시장에 부담", "시장에 우호"]
        for code, symbol in [("NQ", "NQ=F"), ("ETH", "ETHUSDT"), ("KOSPI", "^KS11")]:
            next(x for x in app.get("button_group") if x.label == "분석할 시장").set_value(code).run()
            assert not app.exception and not app.error
            assert (
                json.loads(app.get("plotly_chart")[0].proto.spec)["layout"]["meta"]["btcLive"]["symbol"]
                == symbol
            )


def test_daily_delayed_open_labels_keep_the_trading_date_and_actual_close():
    data = payload()
    row = data["chart"]["result"][0]
    row["timestamp"][-1] += 3600
    frame = parse_history(data, "1d", NOW, "KOSPI")
    assert frame.index[-1] == pd.Timestamp("2026-10-16T00:00Z")
    assert bar_closes(frame, frame.index[-1], "1d") == pd.Timestamp("2026-10-16T06:30Z")
    starts, _ = calendar_bars(2026, 2026, "1d", "KOSPI")
    for holiday in ["2026-06-03T00:00Z", "2026-07-17T00:00Z"]:
        assert pd.Timestamp(holiday) not in starts


def test_terminal_quote_snapshot_is_not_a_complete_intraday_candle():
    data = payload("1h")
    quote = data["chart"]["result"][0]["indicators"]["quote"][0]
    for name in ("open", "high", "low", "close"):
        quote[name][-1] = 2800
    quote["volume"][-1] = 0
    frame = parse_history(data, "1h", NOW, "KOSPI")
    assert len(frame) == 399
    assert frame.index[-1].hour == 5
