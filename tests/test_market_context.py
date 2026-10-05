"""Public sources: instrument identity, feed safety, bounded concurrency and freshness."""

from dataclasses import replace
from datetime import datetime, timedelta
from email.utils import format_datetime
from threading import Event
import time
from xml.sax.saxutils import escape

import pytest
import requests

from btc_analyzer.data.market_context import (
    FeedState,
    MarketContext,
    MarketContextService,
    UTC,
    classify_headline,
    parse_news,
    parse_quote,
)
from btc_analyzer.ui.market_context import macro_cards, news_card

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def quote_payload(symbol="NQ=F", price=22345.5, age=15):
    stamp = int((NOW - timedelta(minutes=age)).timestamp())
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": symbol,
                        "regularMarketPrice": price,
                        "regularMarketTime": stamp,
                        "instrumentType": "FUTURE" if symbol == "NQ=F" else "INDEX",
                        "chartPreviousClose": price / 1.01,
                        "exchangeDataDelayedBy": 15,
                    },
                    "timestamp": [stamp - 300, stamp],
                    "indicators": {"quote": [{"close": [None, price]}]},
                }
            ]
        }
    }


@pytest.mark.parametrize("symbol,price", [("NQ=F", 22345.5), ("^TNX", 4.25)])
def test_instruments_and_units_are_exact_and_no_tnx_division(symbol, price):
    parsed = parse_quote(quote_payload(symbol, price), symbol, NOW)
    assert parsed.price == price
    assert parsed.points == (price,)
    assert parsed.change == pytest.approx(0.01)
    assert parsed.delay_minutes == 15
    with pytest.raises(ValueError, match="Unexpected instrument"):
        parse_quote(quote_payload("^NDX", price), symbol, NOW)


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), True, "4.25", None])
def test_invalid_quotes_never_become_fake_values(price):
    payload = quote_payload("^TNX", 4.25)
    payload["chart"]["result"][0]["meta"]["regularMarketPrice"] = price
    with pytest.raises(ValueError):
        parse_quote(payload, "^TNX", NOW)


def test_quote_age_yield_scale_and_future_source_timestamps():
    for payload in (quote_payload(age=-1), quote_payload(age=8 * 1440), quote_payload("^TNX", 42.5)):
        with pytest.raises(ValueError):
            parse_quote(payload, payload["chart"]["result"][0]["meta"]["symbol"], NOW)
    old = parse_quote(quote_payload(age=3 * 1440), "NQ=F", NOW)
    html = macro_cards(MarketContext((FeedState("nq", old, NOW),)), NOW)
    assert "마지막 거래 시세" in html and "KST" in html and "실시간" not in html
    failed = macro_cards(MarketContext((FeedState("nq", error="자료원 연결 지연"),)), NOW)
    assert "—" in failed and "22,345" not in failed and "iframe" not in failed


@pytest.mark.parametrize(
    "title,topic,direction,pending",
    [
        ("Oil surges after supply disruption", "oil", -1, False),
        ("Crude jumps after supply disruption", "oil", -1, False),
        ("유가 하락, 원유 공급 재개", "oil", 1, False),
        ("CPI higher than expected", "inflation", -1, False),
        ("PCE below expectations", "inflation", 1, False),
        ("미국 물가 예상치 상회", "inflation", -1, False),
        ("Federal Reserve cuts rates", "rates", 1, False),
        ("연준 금리 인하 가능성", "rates", 0, True),
        ("Fed expected to cut rates", "rates", 0, True),
        ("Fed rate cut bets rise", "rates", 0, True),
        ("연준 금리 인하 기대 상승", "rates", 0, True),
        ("Fed rate cut cancelled", "rates", 0, False),
        ("중동 휴전 합의 체결", "geopolitics", 1, False),
        ("중동 휴전 합의 무산", "geopolitics", 0, False),
        ("Missile attack escalates war", "geopolitics", -1, False),
        ("Jobs report beats expectations", "economy", 0, False),
        ("CPI preview ahead of release", "inflation", 0, True),
        ("Bitcoin ETF inflows jump", "crypto", 1, False),
        ("Bitcoin ETF outflows jump", "crypto", -1, False),
        ("Oil does not rise", "oil", 0, False),
        ("유가 급등 후 하락", "oil", 0, False),
    ],
)
def test_direction_requires_evidence_and_does_not_invent_release_results(title, topic, direction, pending):
    actual = classify_headline(title)
    assert (actual[0], actual[1], actual[4]) == (topic, direction, pending)


def rss(title="유가 급등", date=NOW, url="https://news.google.com/rss/articles/test"):
    return f"<rss><channel><item><title>{escape(title)} - Example</title><source>Example</source><link>{escape(url)}</link><pubDate>{format_datetime(date, usegmt=True)}</pubDate></item></channel></rss>".encode()


def test_rss_rejects_future_old_and_unsafe_links_and_escapes_content():
    for date in (NOW + timedelta(seconds=1), NOW - timedelta(days=4)):
        assert parse_news(rss(date=date), NOW) == ()
    for link in (
        "javascript:alert(1)",
        "https://news.google.com.evil.test/a",
        "https://user@news.google.com/a",
        "https://news.google.com:444/a",
    ):
        assert parse_news(rss(url=link), NOW) == ()
    for raw in (b"<!DOCTYPE rss><rss/>", b"<!ENTITY x 'test'><rss/>", b"x" * 512001):
        with pytest.raises(ValueError):
            parse_news(raw, NOW)
    item = parse_news(rss("유가 급등 <script>alert(1)</script>"), NOW)[0]
    html = news_card(item)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Example" in html and "KST" in html
    context = MarketContext((FeedState("news_ko", (item,), NOW), FeedState("news_en", (item,), NOW)))
    assert context.news(NOW, fresh_only=True) == (item,)
    assert (
        replace(context, feeds=(FeedState("news_ko", (item,), NOW - timedelta(minutes=11)),)).news(
            NOW, fresh_only=True
        )
        == ()
    )


def await_idle(service):
    end = time.monotonic() + 2
    while time.monotonic() < end:
        snapshot = service.snapshot()
        if not any(feed.loading for feed in snapshot.feeds):
            return snapshot
        time.sleep(0.005)
    raise AssertionError("Background requests did not finish")


def test_blocked_provider_does_not_block_fast_quotes_or_spawn_duplicate_requests():
    release, blocked = Event(), Event()
    calls = []

    def fetch(key, now):
        calls.append(key)
        if key == "nq":
            blocked.set()
            assert release.wait(2)
        return parse_quote(quote_payload("^TNX", 4.25), "^TNX", now) if key == "tnx" else ()

    service = MarketContextService(fetch, lambda: NOW)
    try:
        start = time.monotonic()
        service.snapshot()
        assert time.monotonic() - start < 0.1
        assert blocked.wait(1)
        for _ in range(20):
            snapshot = service.snapshot()
        release.set()
        snapshot = await_idle(service)
        assert snapshot.feed("tnx").value.price == 4.25
        assert sorted(calls) == ["news_en", "news_ko", "nq", "tnx"]
    finally:
        release.set()
        service.close()


def test_refresh_failure_keeps_last_good_and_honors_retry_after():
    clock = [NOW]
    calls = []
    quote = parse_quote(quote_payload(), "NQ=F", NOW)

    def fetch(key, now):
        calls.append(key)
        if now > NOW and key == "nq":
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "600"
            raise requests.HTTPError(response=response)
        return quote if key == "nq" else ()

    service = MarketContextService(fetch, lambda: clock[0])
    try:
        await_idle(service)
        clock[0] += timedelta(seconds=61)
        failed = await_idle(service).feed("nq")
        assert failed.value is quote and failed.error and failed.updated_at == NOW
        count = calls.count("nq")
        clock[0] += timedelta(seconds=120)
        await_idle(service)
        assert calls.count("nq") == count
    finally:
        service.close()


def test_source_generation_change_releases_previous_shared_service(monkeypatch):
    from btc_analyzer.ui import market_context as ui

    class Service:
        closed = False

        def close(self):
            self.closed = True

    ui.cached_context_service.clear()
    monkeypatch.setattr(ui, "MarketContextService", Service)
    monkeypatch.setattr(ui, "__checkout_signature__", "test-first-generation")
    before = ui.context_service()
    assert ui.context_service() is before
    monkeypatch.setattr(ui, "__checkout_signature__", "test-new-generation")
    after = ui.context_service()
    assert after is not before and before.closed and not after.closed
    ui.cached_context_service.clear()
    assert after.closed
