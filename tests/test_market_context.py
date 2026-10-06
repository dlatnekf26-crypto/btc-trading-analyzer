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
    crypto_relevance,
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
                        "instrumentType": "FUTURE" if symbol in ("NQ=F", "CL=F") else "INDEX",
                        "chartPreviousClose": price / 1.01,
                        "exchangeDataDelayedBy": 15,
                    },
                    "timestamp": [stamp - 300, stamp],
                    "indicators": {"quote": [{"close": [None, price]}]},
                }
            ]
        }
    }


@pytest.mark.parametrize("symbol,price", [("NQ=F", 22345.5), ("CL=F", 87.42), ("^TNX", 4.25), ("^TYX", 4.80)])
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


@pytest.mark.parametrize("symbol", ["CL=F", "^TYX"])
def test_new_quotes_keep_exact_instrument_units_and_reject_mislabeled_feeds(symbol):
    payload = quote_payload(symbol, 87.42 if symbol == "CL=F" else 4.80)
    assert parse_quote(payload, symbol, NOW).symbol == symbol
    meta = payload["chart"]["result"][0]["meta"]
    meta["instrumentType"] = "INDEX" if symbol == "CL=F" else "FUTURE"
    with pytest.raises(ValueError):
        parse_quote(payload, symbol, NOW)
    payload = quote_payload(symbol, 4.8 if symbol == "^TYX" else 87.42)
    payload["chart"]["result"][0]["meta"]["currency"] = "KRW"
    with pytest.raises(ValueError):
        parse_quote(payload, symbol, NOW)
    if symbol == "^TYX":
        with pytest.raises(ValueError, match="yield units"):
            parse_quote(quote_payload(symbol, 48), symbol, NOW)


def test_four_macro_cards_show_wti_barrels_and_both_yields_as_percentage_points():
    context = MarketContext(
        tuple(
            FeedState(key, parse_quote(quote_payload(symbol, price), symbol, NOW), NOW)
            for key, symbol, price in (
                ("nq", "NQ=F", 22345.5),
                ("oil", "CL=F", 87.42),
                ("tnx", "^TNX", 4.25),
                ("tyx", "^TYX", 4.8),
            )
        )
    )
    html = macro_cards(context, NOW)
    assert html.count('class="btc-macro-card"') == 4
    assert "WTI 원유 선물" in html and "USD/배럴" in html
    assert "미국채 30년물" in html and "CBOE ^TYX" in html and "+0.048%p" in html
    assert "실시간" not in html
    payload = quote_payload("^TYX", 4.8)
    payload["chart"]["result"][0]["meta"]["exchangeDataDelayedBy"] = True
    assert parse_quote(payload, "^TYX", NOW).delay_minutes is None


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


def rss(
    title="비트코인 시장, 유가 급등",
    date=NOW,
    url="https://news.google.com/rss/articles/test",
    source="Example",
):
    return f"<rss><channel><item><title>{escape(title)} - {escape(source)}</title><source>{escape(source)}</source><link>{escape(url)}</link><pubDate>{format_datetime(date, usegmt=True)}</pubDate></item></channel></rss>".encode()


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
    item = parse_news(rss("비트코인 유가 급등 <script>alert(1)</script>"), NOW)[0]
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


@pytest.mark.parametrize(
    "title,accepted",
    [
        ("Oil surges after supply disruption", False),
        ("Federal Reserve cuts rates", False),
        ("S&P 500 ETF inflows jump", False),
        ("비트코인 피자 축제 개최", False),
        ("Bitcoin ETF inflows jump", True),
        ("Ethereum price falls ahead of CPI", True),
        ("비트코인, 연준 금리 인하 주목", True),
        ("유가 급등에 비트코인 시장 위험 선호 약화", True),
        ("유가 급등, 비트코인과 무관", False),
        ("Oil surge unrelated to Bitcoin", False),
        ("연준 금리 인하 - Bitcoin Exchange", False),
    ],
)
def test_only_coin_linked_market_events_enter_feed_and_cached_news(title, accepted):
    raw = (
        rss(title.removesuffix(" - Bitcoin Exchange"), source="Bitcoin Exchange")
        if title.endswith(" - Bitcoin Exchange")
        else rss(title)
    )
    assert bool(parse_news(raw, NOW)) is accepted
    # A syndicator name containing 'Bitcoin' cannot supply headline relevance.
    if title.endswith(" - Bitcoin Exchange"):
        assert crypto_relevance(title.removesuffix(" - Bitcoin Exchange")) is None
    else:
        assert bool(crypto_relevance(title)) is accepted
    item = parse_news(rss(), NOW)[0]
    generic = replace(item, title="Federal Reserve cuts rates")
    assert MarketContext((FeedState("news_ko", (generic, item), NOW),)).news(NOW) == (item,)


def test_fx_requires_market_pair_currency_and_quote_refreshes_independently_of_news():
    payload = quote_payload("KRW=X", 1345.5, age=0)
    payload["chart"]["result"][0]["meta"].update(instrumentType="CURRENCY", currency="KRW")
    value = parse_quote(payload, "KRW=X", NOW)
    assert value.price == 1345.5
    payload["chart"]["result"][0]["meta"]["currency"] = "USD"
    with pytest.raises(ValueError, match="USD/KRW"):
        parse_quote(payload, "KRW=X", NOW)
    clock, calls = [NOW], []

    def fetch(key, now):
        calls.append(key)
        return value if key == "fx" else ()

    service = MarketContextService(fetch, lambda: clock[0])
    try:
        await_idle(service)
        clock[0] += timedelta(seconds=11)
        await_idle(service)
        assert calls.count("fx") == 2 and calls.count("nq") == 2
        assert calls.count("news_ko") == 1 and calls.count("news_en") == 1
        clock[0] = NOW + timedelta(seconds=61)
        await_idle(service)
        assert calls.count("news_ko") == 2 and calls.count("news_en") == 2
    finally:
        service.close()


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
        assert sorted(calls) == ["fx", "news_en", "news_ko", "nq", "oil", "tnx", "tyx"]
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
