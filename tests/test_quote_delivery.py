"""REST recovery, extended-session identity and quote delivery without live ticks."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
import requests

from btc_analyzer.data import market_context
from btc_analyzer.data.market_context import FeedState, MarketContext, parse_quote
from btc_analyzer.ui.quote_snapshot import quote_display, snapshot_json

NOW = datetime(2026, 10, 16, 23, 59, 50, tzinfo=timezone.utc)


def quote_payload():
    def stamp(hour, minute=0):
        return int(NOW.replace(hour=hour, minute=minute, second=0).timestamp())

    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "instrumentType": "EQUITY",
                        "exchangeTimezoneName": "America/New_York",
                        "dataGranularity": "1m",
                        "regularMarketPrice": 100,
                        "regularMarketTime": stamp(20) + 1,
                        "chartPreviousClose": 98,
                        "currentTradingPeriod": {
                            "pre": {"start": stamp(8), "end": stamp(13, 30)},
                            "post": {"start": stamp(20), "end": stamp(23, 59) + 60},
                        },
                    },
                    "timestamp": [stamp(19, 59), stamp(20, 30), stamp(23, 59)],
                    "indicators": {"quote": [{"close": [100, 101, 102]}]},
                }
            ]
        }
    }


def test_regular_and_extended_prices_keep_their_actual_reference_and_session():
    q = parse_quote(quote_payload(), "AAPL", NOW)
    assert q.price == 100 and q.change == pytest.approx(100 / 98 - 1)
    assert q.extended.price == 102 and q.extended.session == "post"
    assert q.points == (100, 101, 102)
    assert quote_display(q)["change"] == pytest.approx(2)
    rows = json.loads(snapshot_json(MarketContext((FeedState("aapl", q, NOW),))))
    row = next(row for row in rows if row["symbol"] == "AAPL")
    assert row["price"] == 102 and row["regularPrice"] == 100 and row["session"] == "post"
    assert row["asOf"] > row["regularAsOf"]


@pytest.mark.parametrize("bad", [None, True, -1, 0, float("nan"), float("inf"), "104"])
def test_invalid_extended_closes_never_replace_a_valid_quote(bad):
    payload = quote_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [100, bad, bad]
    q = parse_quote(payload, "AAPL", NOW)
    assert q.extended is None and quote_display(q)["price"] == 100


def test_premarket_uses_the_previous_regular_close_and_requires_provider_periods():
    payload = quote_payload()
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    now = NOW.replace(hour=12)
    meta["regularMarketTime"] -= 86400
    result["timestamp"] = [int(now.timestamp()) - 60]
    result["indicators"]["quote"][0]["close"] = [99]
    q = parse_quote(payload, "AAPL", now)
    assert q.extended.price == 99 and q.extended.session == "pre"
    del meta["currentTradingPeriod"]
    assert parse_quote(payload, "AAPL", now).extended is None


def test_future_or_regular_session_values_are_not_claimed_as_after_hours():
    payload = quote_payload()
    result = payload["chart"]["result"][0]
    result["timestamp"] = [int(NOW.timestamp()) + 60, int(NOW.replace(hour=19).timestamp())]
    result["indicators"]["quote"][0]["close"] = [200, 300]
    assert parse_quote(payload, "AAPL", NOW).extended is None
    for symbol, currency, zone, kind in [
        ("005930.KS", "KRW", "Asia/Seoul", "EQUITY"),
        ("^GSPC", "USD", "America/New_York", "INDEX"),
    ]:
        other = deepcopy(quote_payload())
        other["chart"]["result"][0]["meta"].update(
            symbol=symbol, currency=currency, exchangeTimezoneName=zone, instrumentType=kind
        )
        assert parse_quote(other, symbol, NOW).extended is None


def test_quote_snapshot_keeps_last_good_on_failure_without_leaking_another_symbol():
    q = parse_quote(quote_payload(), "AAPL", NOW)
    context = MarketContext((FeedState("aapl", q, NOW, "자료원 연결 지연"), FeedState("nvda", q, NOW)))
    rows = {row["symbol"]: row for row in json.loads(snapshot_json(context))}
    assert rows["AAPL"]["price"] == 102 and rows["AAPL"]["error"] == "자료원 연결 지연"
    assert "price" not in rows["NVDA"]


def test_minute_failure_uses_validated_daily_metadata_and_rate_limits_are_respected(monkeypatch):
    calls = []

    def download(url):
        calls.append(url)
        if "interval=1m" in url:
            raise requests.Timeout("minute series unavailable")
        payload = quote_payload()
        payload["chart"]["result"][0]["meta"]["dataGranularity"] = "1d"
        return json.dumps(payload).encode()

    monkeypatch.setattr(market_context, "_download", download)
    q = market_context.fetch_feed("aapl", NOW)
    assert q.price == 100 and q.extended is None
    assert len(calls) == 2 and "includePrePost=true" in calls[0] and "interval=1d&range=1mo" in calls[1]

    def limited(url):
        calls.append(url)
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(response=response)

    calls.clear()
    monkeypatch.setattr(market_context, "_download", limited)
    with pytest.raises(requests.HTTPError):
        market_context.fetch_feed("aapl", NOW)
    assert len(calls) == 1
