"""Read-only NXT adapter: exact times, authentication reuse, and stale-data rejection."""

from datetime import datetime, timedelta, timezone
import pytest
from btc_analyzer.data.nxt_quotes import NXTClient, parse_nxt

NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)  # 17:00 KST


def payload(price="215000", stamp="165900", day="20261026"):
    return {"rt_cd": "0", "output2": [{"stck_bsop_date": day, "stck_cntg_hour": stamp, "stck_prpr": price}]}


def test_nxt_accepts_only_real_recent_extended_trades():
    q = parse_nxt(payload(), NOW)
    assert q.price == 215000 and q.session == "post" and q.source == "KIS NXT"
    for bad in [
        payload(price=True),
        payload(price="NaN"),
        payload(stamp="170001"),
        payload(stamp="150000"),
        payload(day="20261023"),
    ]:
        with pytest.raises(ValueError):
            parse_nxt(bad, NOW)


def test_broker_requests_are_read_only_nxt_and_tokens_are_reused(monkeypatch):
    client = NXTClient("test-key", "test-secret")
    calls = []

    def request(method, path, **kw):
        calls.append((method, path, kw))
        return {"access_token": "test-token", "expires_in": 86400} if method == "POST" else payload()

    monkeypatch.setattr(client, "_json", request)
    for _ in range(2):
        assert client.fetch("nxt_samsung", NOW).price == 215000
    assert len([c for c in calls if c[0] == "POST"]) == 1
    assert all(c[2]["params"]["FID_COND_MRKT_DIV_CODE"] == "NX" for c in calls if c[0] == "GET")
    assert client.fetch("nxt_samsung", NOW + timedelta(hours=5)).price == 215000
    assert len(calls) == 3  # Closed market keeps last verified trade without requesting.


def test_configured_broker_overlays_a_newer_trade_without_replacing_regular_history(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from btc_analyzer.data.market_context import MacroQuote, MarketContext, FeedState
    from btc_analyzer.ui import market_context as ui

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    original = MacroQuote(
        "005930.KS", 214000, NOW - timedelta(minutes=90), NOW - timedelta(minutes=1), (), 0.01, 15
    )
    base = MarketContext((FeedState("samsung", original, NOW),))
    extra = MarketContext((FeedState("nxt_samsung", parse_nxt(payload(), NOW), NOW),))
    monkeypatch.setattr(ui, "datetime", Clock)
    monkeypatch.setattr(ui, "_nxt_credentials", lambda: ("test-key", "test-secret"))
    monkeypatch.setattr(ui, "context_service", lambda: SimpleNamespace(snapshot=lambda: base))
    monkeypatch.setattr(ui, "nxt_service", lambda *args: SimpleNamespace(snapshot=lambda: extra))
    value = ui.current_context().feed("samsung").value
    assert value.extended.source == "KIS NXT" and value.extended.price == 215000
    assert value.price == original.price and original.extended is None
    assert value.delay_minutes is None and value.fetched_at == NOW
    monkeypatch.setattr(
        ui, "nxt_service", lambda *args: SimpleNamespace(snapshot=lambda: replace(extra, feeds=()))
    )
    assert ui.current_context().feed("samsung").value == original
