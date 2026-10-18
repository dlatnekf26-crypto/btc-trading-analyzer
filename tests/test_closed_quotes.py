"""A quiet market retains genuine prices, dates and a prompt opening refresh."""

from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest

from btc_analyzer.data.market_context import FeedState, MarketContext, MarketContextService, parse_quote
from btc_analyzer.data.quote_hours import market_hours
from btc_analyzer.ui.chart_reader import reader_html
from btc_analyzer.ui.market_board import quote_fields
from test_market_context import await_idle
from test_quote_delivery import quote_payload


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "symbol,now,phase,boundary",
    [
        ("005930.KS", "2026-10-16T06:15", "regular", "2026-10-16T06:30"),
        ("005930.KS", "2026-10-18T08:00", "closed", "2026-10-19T00:00"),
        ("005930.KS", "2026-11-19T00:15", "closed", "2026-11-19T01:00"),
        ("005930.KS", "2026-11-19T06:45", "regular", "2026-11-19T07:30"),
        ("005930.KS", "2026-01-02T00:15", "closed", "2026-01-02T01:00"),
        ("AAPL", "2026-10-18T08:00", "closed", "2026-10-19T08:00"),
        ("AAPL", "2026-10-19T08:00", "pre", "2026-10-19T13:30"),
        ("AAPL", "2026-10-19T20:30", "post", "2026-10-20T00:00"),
        ("^GSPC", "2026-10-19T20:30", "closed", "2026-10-20T13:30"),
        ("AAPL", "2026-11-27T18:00", "post", "2026-11-27T22:00"),
        ("NQ=F", "2026-10-18T20:00", "closed", "2026-10-18T22:00"),
    ],
)
def test_actual_exchange_boundaries_including_early_close_dst_and_special_krx(symbol, now, phase, boundary):
    assert market_hours(symbol, at(now)) == (phase, at(boundary))


def daily_payload():
    payload = quote_payload()
    result = payload["chart"]["result"][0]
    result["meta"].update(dataGranularity="1d", regularMarketPrice=None, regularMarketTime=None)
    result["timestamp"] = [
        int(at(day + "T13:30").timestamp()) for day in ["2026-10-15", "2026-10-16", "2026-10-19"]
    ]
    result["indicators"]["quote"] = [
        {
            "open": [97, 99, 101],
            "high": [99, 102, 105],
            "low": [96, 98, 100],
            "close": [98, 100, 104],
            "volume": [10, 20, 30],
        }
    ]
    return payload


def test_missing_current_quote_uses_completed_daily_close_never_open_days_partial_close():
    q = parse_quote(daily_payload(), "AAPL", at("2026-10-19T14:00"))
    assert q.price == 100 and q.as_of == at("2026-10-16T20:00")
    assert q.day_high == 102 and q.day_low == 98 and q.volume == 20
    assert q.change == pytest.approx(100 / 98 - 1)
    assert q.extended is None and 104 not in q.points


def test_close_fallback_still_rejects_wrong_currency_and_invalid_bars():
    payload = daily_payload()
    payload["chart"]["result"][0]["meta"]["currency"] = "KRW"
    with pytest.raises(ValueError):
        parse_quote(payload, "AAPL", at("2026-10-19T14:00"))
    payload = daily_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["high"] = [1, 1, 1]
    with pytest.raises(ValueError):
        parse_quote(payload, "AAPL", at("2026-10-19T14:00"))


def test_daily_fallback_uses_previous_session_not_monthly_chart_reference():
    payload = daily_payload()
    meta = payload["chart"]["result"][0]["meta"]
    meta.update(
        regularMarketPrice=104,
        regularMarketTime=int(at("2026-10-19T14:00").timestamp()),
        range="1mo",
        chartPreviousClose=50,
    )
    q = parse_quote(payload, "AAPL", at("2026-10-19T14:00"))
    assert q.price == 104 and q.change == pytest.approx(0.04)
    # With Friday's closing quote the reference is Thursday, not Friday itself.
    meta.update(regularMarketPrice=100, regularMarketTime=int(at("2026-10-16T20:00").timestamp()))
    q = parse_quote(payload, "AAPL", at("2026-10-19T14:00"))
    assert q.change == pytest.approx(100 / 98 - 1)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["high"] = [1, 1, 1]
    q = parse_quote(payload, "AAPL", at("2026-10-19T14:00"))
    assert q.price == 100 and q.change is None


def test_quiet_refreshes_reduce_calls_and_resume_at_next_open():
    clock, calls = [at("2026-10-18T08:00")], []
    service = MarketContextService(lambda key, now: calls.append(key), lambda: clock[0], keys=("aapl", "oil"))
    try:
        await_idle(service)
        for seconds in (30, 60, 120, 299):
            clock[0] = at("2026-10-18T08:00") + timedelta(seconds=seconds)
            await_idle(service)
        assert calls.count("aapl") == 1 and calls.count("oil") == 5
        clock[0] = at("2026-10-18T08:05")
        await_idle(service)
        assert calls.count("aapl") == 2
        clock[0] = at("2026-10-19T07:59:50")
        await_idle(service)
        clock[0] = at("2026-10-19T08:00")
        await_idle(service)
        assert calls.count("aapl") == 4
        clock[0] += timedelta(seconds=29)
        await_idle(service)
        assert calls.count("aapl") == 4
        clock[0] += timedelta(seconds=1)
        await_idle(service)
        assert calls.count("aapl") == 5
    finally:
        service.close()


def test_closed_card_keeps_after_hours_and_regular_prices_with_their_date(monkeypatch):
    from btc_analyzer.ui import market_board, quote_snapshot

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at("2026-10-18T08:00").astimezone(tz)

    monkeypatch.setattr(market_board, "datetime", Clock)
    monkeypatch.setattr(quote_snapshot, "market_hours", lambda symbol: ("closed", at("2026-10-19T08:00")))
    q = parse_quote(quote_payload(), "AAPL", at("2026-10-16T23:59:50"))
    html = quote_fields("AAPL", context=MarketContext((FeedState("aapl", q),)))
    assert "$102.00" in html and "장 마감" in html and "장후 마지막 거래가" in html
    assert "10.17 08:59" in html and 'data-quote-field="regular">100.00' in html
    rows = json.loads(quote_snapshot.snapshot_json(MarketContext((FeedState("aapl", q),))))
    row = next(row for row in rows if row["symbol"] == "AAPL")
    assert row["marketState"] == "closed" and row["price"] == 102 and row["regularPrice"] == 100


def test_stock_reader_starts_with_an_explicit_confirmed_bar_price():
    frame = pd.DataFrame(
        {"open": [99], "high": [102], "low": [98], "close": [100.0]},
        index=pd.DatetimeIndex(["2026-10-16T13:30Z"]),
    )
    html = reader_html(frame, "1d", "AAPL", (), False)
    assert 'data-field="current">100.00' in html and "마지막 가격" in html
    assert "10.16 22:30 KST · 마지막 확정 봉 (1d)" in html
