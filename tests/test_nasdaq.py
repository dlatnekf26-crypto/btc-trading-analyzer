"""Exchange sessions, source identity and leakage checks for NQ analysis."""

import pandas as pd
import pytest

from btc_analyzer.data.nasdaq import calendar_bars, parse_history, aggregate, trading_dates
from btc_analyzer.indicators.core import indicators
from btc_analyzer.market_clock import gap_groups, bar_closes

NOW = pd.Timestamp("2026-10-17T12:00Z")


def payload():
    starts, ends = calendar_bars(2024, 2026, "1d")
    index = starts[ends <= NOW][-300:]
    prices = [20000 + i for i in range(len(index))]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "NQ=F",
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                        "dataGranularity": "1d",
                    },
                    "timestamp": (index.asi8 // 1_000_000_000).tolist(),
                    "indicators": {
                        "quote": [
                            {
                                "open": prices,
                                "high": [n + 10 for n in prices],
                                "low": [n - 10 for n in prices],
                                "close": prices,
                                "volume": [1000] * len(index),
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_sessions_preserve_weekend_holiday_dst_but_reset_for_missing_trading_day():
    frame = parse_history(payload(), "1d", NOW)
    assert len(set(gap_groups(frame, "1d"))) == 1
    feature = indicators(frame, timeframe="1d")
    assert pd.notna(feature.ema_200.iloc[-1]) and feature.bars_since_gap.iloc[-1] == 300
    assert bar_closes(frame, frame.index[-1], "1d") == pd.Timestamp("2026-10-16T21:00Z")
    dates = trading_dates(pd.Timestamp("2026-10-30T21:00Z"), "1d", 3)
    assert dates[1] == pd.Timestamp("2026-11-02T22:00Z")  # DST ends over the weekend.
    missing = frame.drop(frame.index[-5])
    broken = indicators(missing, timeframe="1d")
    assert broken.bars_since_gap.iloc[-1] == 4 and pd.isna(broken.ema_20.iloc[-1])


def test_aggregation_withholds_a_week_with_a_missing_open_day():
    frame = parse_history(payload(), "1d", NOW)
    week = aggregate(frame, "1w", NOW)
    damaged = aggregate(frame.drop(frame.index[-3]), "1w", NOW)
    assert week.index[-1] not in damaged.index
    assert not (bar_closes(week, week.index, "1w") > NOW).any()


@pytest.mark.parametrize(
    "field,value",
    [("symbol", "BTC-USD"), ("currency", "KRW"), ("dataGranularity", "1mo"), ("exchangeTimezoneName", "UTC")],
)
def test_other_assets_units_and_silently_resampled_data_are_rejected(field, value):
    data = payload()
    data["chart"]["result"][0]["meta"][field] = value
    with pytest.raises(ValueError):
        parse_history(data, "1d", NOW)


def test_selected_nq_has_own_chart_forecast_and_returns_to_crypto(tmp_path, monkeypatch):
    from pathlib import Path
    import json
    import sys
    from scripts.offline_ui_fixture import analysis_app

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from offline_ui_fixture import offline_market_data

    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path))
    with offline_market_data(root):
        app = analysis_app(root / "web_app.py", default_timeout=60).run()
        next(x for x in app.get("button_group") if x.label == "분석할 시장").set_value("NQ").run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        assert spec["layout"]["meta"]["btcLive"]["symbol"] == "NQ=F"
        assert any("공개 지연 자료" in x.value for x in app.caption)
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        meta = spec["layout"]["meta"]["btcLive"]
        assert meta["symbol"] == "NQ=F" and len(meta["indicatorOverlays"]) == 6
        assert meta["liveIndices"] == [] and not any("실시간" in t["name"] for t in spec["data"])
        next(x for x in app.get("button_group") if x.label == "분석할 시장").set_value("ETH").run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        assert spec["layout"]["meta"]["btcLive"]["symbol"] == "ETHUSDT"


@pytest.mark.parametrize("tf", ["5m", "15m"])
def test_short_nq_sessions_stay_bounded_and_ichimoku_skips_weekend(tf):
    from btc_analyzer.market_clock import shift_bars

    starts, ends = calendar_bars("2026-10-01", "2026-10-30", tf)
    index = starts[ends <= NOW][-600:]
    frame = pd.DataFrame(
        {"open": 20000.0, "high": 20010.0, "low": 19990.0, "close": 20000.0, "volume": 100.0}, index=index
    )
    frame.attrs = {
        "market": "NQ",
        "bar_starts": tuple(map(int, starts.asi8)),
        "bar_ends": tuple(map(int, ends.asi8)),
        "timeframe": tf,
    }
    feature = indicators(frame, timeframe=tf)
    assert feature.bars_since_gap.iloc[-1] == 600 and pd.notna(feature.ema_200.iloc[-1])
    shifted = shift_bars(frame, frame.index[-1:], tf, 26)
    assert shifted[0].weekday() == 0
    assert len(starts) < 7000
