"""Stock identity, currency, actual exchange sessions and shared analysis routing."""

from copy import deepcopy
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.assets import STOCK_MARKETS, SESSION_MARKETS, EXCHANGE_HISTORY
from btc_analyzer.data.exchange_history import calendar_bars, parse_history, aggregate, horizon_bars
from btc_analyzer.data.market_context import parse_quote
from btc_analyzer.market_clock import bar_closes, gap_groups

NOW = pd.Timestamp("2026-10-18T12:00Z")


def stock_payload(code, timeframe="1d", count=400):
    asset, venue = SESSION_MARKETS[code], EXCHANGE_HISTORY[code]
    starts, ends = calendar_bars(2025, 2027, timeframe, code)
    index = starts[
        (ends <= NOW) & (starts >= pd.Timestamp(asset.listed, tz=venue.timezone).tz_convert("UTC"))
    ][-count:]
    price = 100 + np.arange(len(index)) * 0.1 + np.sin(np.arange(len(index)) / 8)
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": asset.symbol,
                        "currency": venue.currency,
                        "exchangeTimezoneName": venue.timezone,
                        "instrumentType": venue.kind,
                        "dataGranularity": timeframe,
                        "regularMarketPrice": float(price[-1]),
                        "regularMarketTime": int(NOW.timestamp() - 900),
                        "chartPreviousClose": float(price[-1] / 1.01),
                        "exchangeDataDelayedBy": 15,
                        "regularMarketDayHigh": float(price[-1] + 2),
                        "regularMarketDayLow": float(price[-1] - 2),
                        "regularMarketVolume": 1234,
                    },
                    "timestamp": (index.asi8 // 1_000_000_000).tolist(),
                    "indicators": {
                        "quote": [
                            {
                                "open": price.tolist(),
                                "high": (price + 1).tolist(),
                                "low": (price - 1).tolist(),
                                "close": price.tolist(),
                                "volume": np.full(len(index), 10000).tolist(),
                            }
                        ]
                    },
                }
            ]
        }
    }


@pytest.mark.parametrize(
    "code,pair,currency",
    [
        ("SAMSUNG", "005930.KS", "KRW"),
        ("SKHYNIX", "000660.KS", "KRW"),
        ("SAMSUNG_EM", "009150.KS", "KRW"),
        ("LS_ELECTRIC", "010120.KS", "KRW"),
        ("AAPL", "AAPL", "USD"),
        ("NVDA", "NVDA", "USD"),
        ("MU", "MU", "USD"),
        ("SNDK", "SNDK", "USD"),
    ],
)
def test_stock_identity_quote_and_closed_daily_bars(code, pair, currency):
    asset, venue = STOCK_MARKETS[code], EXCHANGE_HISTORY[code]
    assert asset.symbol == pair and venue.currency == currency and venue.unit == currency
    payload = stock_payload(code)
    frame = parse_history(payload, "1d", NOW, code)
    assert not frame.empty and frame.attrs["market"] == code
    assert (bar_closes(frame, frame.index, "1d") <= NOW).all()
    assert len(set(gap_groups(frame, "1d"))) == 1
    quote = parse_quote(payload, pair, NOW.to_pydatetime())
    assert quote.day_high > quote.price > quote.day_low and quote.volume == 1234
    for key, bad in [
        ("symbol", "ETHUSDT"),
        ("currency", "KRW" if currency == "USD" else "USD"),
        ("instrumentType", "INDEX"),
        ("exchangeTimezoneName", "UTC"),
    ]:
        wrong = deepcopy(payload)
        wrong["chart"]["result"][0]["meta"][key] = bad
        with pytest.raises(ValueError):
            parse_history(wrong, "1d", NOW, code)
        with pytest.raises(ValueError):
            parse_quote(wrong, pair, NOW.to_pydatetime())


@pytest.mark.parametrize("tf", ["5m", "15m", "1h", "4h", "1d", "1w", "1M"])
@pytest.mark.parametrize("market", ["AAPL", "SP500"])
def test_us_equity_holidays_early_close_and_forecast_use_cash_sessions(tf, market):
    starts, ends = calendar_bars("2026-11-26", "2026-11-27", tf, market)
    assert len(starts) > 0
    extended = market == "AAPL" and tf in ("5m", "15m", "1h", "4h")
    assert starts[0].tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M") == (
        "2026-11-27 04:00" if extended else "2026-11-27 09:30"
    )
    # Thanksgiving is absent; Friday's last bar closes at 13:00, including daily bars.
    assert ends[-1].tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M") == (
        "2026-11-27 17:00" if extended else "2026-11-27 13:00"
    )
    assert (ends > starts).all()


@pytest.mark.parametrize("code", ["SAMSUNG", "SKHYNIX"])
def test_korean_stocks_share_delayed_openings_and_holidays(code):
    for day in ("2026-01-02", "2026-11-19"):
        starts, ends = calendar_bars(day, day, "1h", code)
        assert starts[0].tz_convert("Asia/Seoul").hour == 10
        assert (ends > starts).all()
    assert len(calendar_bars("2026-07-17", "2026-07-17", "1d", code)[0]) == 0


@pytest.mark.parametrize("code", list(STOCK_MARKETS))
def test_aggregated_four_hour_week_month_candles_keep_their_market(code):
    hourly = parse_history(stock_payload(code, "1h", 600), "1h", NOW, code)
    daily = parse_history(stock_payload(code), "1d", NOW, code)
    for tf, source in (("4h", hourly), ("1w", daily), ("1M", daily)):
        frame = aggregate(source, tf, NOW)
        assert not frame.empty and frame.attrs["market"] == code
        assert (bar_closes(frame, frame.index, tf) <= NOW).all()
    assert horizon_bars(bar_closes(daily, daily.index[-1], "1d"), "1w", code) in range(3, 6)


def test_sandisk_history_never_reuses_the_old_pre_2025_ticker():
    payload = stock_payload("SNDK")
    payload["chart"]["result"][0]["timestamp"] = [
        stamp - int(pd.Timedelta(days=3650).total_seconds())
        for stamp in payload["chart"]["result"][0]["timestamp"]
    ]
    with pytest.raises(ValueError, match="유효한 시장 봉"):
        parse_history(payload, "1d", NOW, "SNDK")


def test_sp500_is_the_actual_index_with_regular_us_sessions():
    payload = stock_payload("SP500")
    frame = parse_history(payload, "1d", NOW, "SP500")
    assert frame.attrs["market"] == "SP500" and len(frame) == 400
    assert parse_quote(payload, "^GSPC", NOW.to_pydatetime()).symbol == "^GSPC"
    assert horizon_bars(bar_closes(frame, frame.index[-1], "1d"), "1w", "SP500") == 5
    for field, value in (("symbol", "SPY"), ("instrumentType", "ETF"), ("currency", "KRW")):
        wrong = deepcopy(payload)
        wrong["chart"]["result"][0]["meta"][field] = value
        with pytest.raises(ValueError):
            parse_quote(wrong, "^GSPC", NOW.to_pydatetime())


@pytest.mark.parametrize("code", [*STOCK_MARKETS, "SP500", "OIL", "TNX", "TYX", "GOLD"])
def test_stock_cards_open_shared_chart_and_forecast_with_correct_units(code, offline_dashboard, monkeypatch):
    from scripts.offline_ui_fixture import analysis_app
    from btc_analyzer.data.service import DataService

    def crypto_fetch(*args, **kwargs):
        pytest.fail("Stock analysis must not collect crypto history")

    monkeypatch.setattr(DataService, "bundle", crypto_fetch)
    app = analysis_app(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=60)
    app.query_params["market"] = code
    app.run()
    assert not app.exception and not app.error and not app.warning
    assert app.button(key="open_" + code)
    assert app.selectbox(key="analysis_asset").value == code
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert spec["layout"]["meta"]["btcLive"]["symbol"] == SESSION_MARKETS[code].symbol
    assert len(spec["layout"]["meta"]["btcLive"]["panels"]) == 2
    app.session_state["dashboard_tab"] = "미래 예측"
    app.run(timeout=60)
    assert not app.exception and not app.error
    assert any("예측 도착일" in item.value for item in app.caption)
    assert any(
        EXCHANGE_HISTORY[code].unit in item.value and 'id="btc-forecast-reader"' in item.value
        for item in app.markdown
    )


def test_us_pre_1985_daily_labels_keep_yahoo_date_but_actual_close():
    starts, ends = calendar_bars("1984-06-01", "1984-06-01", "1d", "MU")
    assert starts[0].tz_convert("America/New_York").strftime("%H:%M") == "09:30"
    assert ends[0].tz_convert("America/New_York").strftime("%H:%M") == "16:00"


def test_concurrent_calendar_builds_are_shared_and_return_independent_copies(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import pandas_market_calendars as calendars
    from btc_analyzer.data import trading_calendar

    original = calendars.get_calendar
    calls = []

    def record(name):
        calls.append(name)
        return original(name)

    monkeypatch.setattr(calendars, "get_calendar", record)
    trading_calendar._schedule.cache_clear()
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(
            pool.map(
                lambda _: trading_calendar.schedule(
                    "XKRX", "2020-01-01", "2027-12-31", ("market_open", "market_close")
                ),
                range(6),
            )
        )
    assert calls == ["XKRX"]
    assert all(frame.equals(frames[0]) for frame in frames)
    frames[0].iloc[0, 0] += pd.Timedelta(hours=1)
    assert frames[0].iloc[0, 0] != frames[1].iloc[0, 0]


def test_short_sandisk_history_withholds_long_forecasts_instead_of_inventing_price(offline_dashboard):
    from scripts.offline_ui_fixture import analysis_app

    app = analysis_app(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=60)
    app.query_params["market"] = "SNDK"
    app.session_state["dashboard_tab"] = "미래 예측"
    app.session_state["forecast_horizon"] = "6mo"
    app.run()
    assert not app.exception and not app.error
    assert not app.get("plotly_chart")
    assert any("서로 겹치지 않는 유사 사례가 3개 이상" in item.value for item in app.info)
    assert not any('id="btc-forecast-reader"' in item.value for item in app.markdown)


@pytest.mark.parametrize("code", ["MSTR", "GOOGL", "TSLA", "META", "HYUNDAI", "LGES", "OIL", "TNX", "TYX"])
def test_new_markets_keep_identity_and_all_chart_intervals(code):
    for tf in ("5m", "15m", "1h", "1d"):
        frame = parse_history(stock_payload(code, tf), tf, NOW, code)
        assert not frame.empty and frame.attrs["market"] == code
        assert (bar_closes(frame, frame.index, tf) <= NOW).all()


def test_us_extended_hourly_windows_preserve_regular_alignment_and_dst():
    for day, utc_hour in (("2026-03-06", 9), ("2026-03-09", 8)):
        starts, ends = calendar_bars(day, day, "1h", "AAPL")
        assert starts[0].hour == utc_hour
        local = starts.tz_convert("America/New_York")
        assert local.strftime("%H:%M").tolist() == [
            "04:00",
            "05:00",
            "06:00",
            "07:00",
            "08:00",
            "09:00",
            "09:30",
            "10:30",
            "11:30",
            "12:30",
            "13:30",
            "14:30",
            "15:30",
            "16:00",
            "17:00",
            "18:00",
            "19:00",
        ]
        assert ends[-1].tz_convert("America/New_York").hour == 20
        assert (ends[:-1] <= starts[1:]).all()


def test_yield_and_oil_use_their_own_hours_and_units():
    starts, ends = calendar_bars("2026-10-22", "2026-10-22", "1h", "TNX")
    assert starts[0].strftime("%H:%M") == "12:20"
    assert ends[-1].strftime("%H:%M") == "19:00"
    assert EXCHANGE_HISTORY["TNX"].unit == "%"
    starts, ends = calendar_bars("2026-10-22", "2026-10-22", "1h", "OIL")
    assert len(starts) == 23 and starts[0].day == 21 and ends[-1].hour == 21
