from dataclasses import replace
from datetime import datetime, timedelta

from btc_analyzer.analysis.move_news import news_bridge
from btc_analyzer.data.market_context import FeedState, MarketContext, NewsItem, UTC

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
ITEM = NewsItem(
    "Bitcoin ETF inflows surge",
    "https://example.com/news",
    "Source",
    NOW - timedelta(minutes=3),
    "crypto",
    1,
    0.5,
    "candidate",
)


def bridge(item=ITEM, **kwargs):
    return news_bridge(MarketContext((FeedState("news_en", (item,), **{"updated_at": NOW, **kwargs}),)), NOW)


def test_fresh_catalyst_links_keep_asset_direction_source_and_time():
    html = bridge()
    assert 'data-assets="BTCUSDT"' in html and 'data-direction="1"' in html
    assert 'data-published="' in html and 'data-fetched="' in html
    assert 'data-source="Source"' in html
    assert 'data-assets="ETHUSDT"' in bridge(replace(ITEM, title="Ethereum exchange hack"))
    assert "BTCUSDT ETHUSDT" in bridge(replace(ITEM, title="Crypto market reacts to Fed rate cut"))
    assert "&lt;img" in bridge(
        replace(ITEM, title="Bitcoin ETF inflows <img src=x>", source='Source"<script>')
    )
    assert "<img" not in bridge(replace(ITEM, title="Bitcoin ETF inflows <img src=x>"))


def test_no_stale_future_failed_speculation_price_only_or_unrelated_causes():
    for item in (
        replace(ITEM, published_at=NOW - timedelta(minutes=31)),
        replace(ITEM, published_at=NOW + timedelta(seconds=1)),
        replace(ITEM, pending=True),
        replace(ITEM, title="Bitcoin surges 5% today"),
        replace(ITEM, title="Bitcoin price jumps in seconds"),
        replace(ITEM, title="Bitcoin price rising, software update"),
        replace(ITEM, title="Bitcoin ETF approval rumor"),
        replace(ITEM, title="유가 급등"),
        replace(ITEM, title="솔라나 코인 해킹 발생"),
        replace(ITEM, url="javascript:alert(1)"),
    ):
        assert "<a " not in bridge(item)
    for kwargs in (
        {"updated_at": None},
        {"updated_at": NOW - timedelta(minutes=3)},
        {"updated_at": NOW + timedelta(seconds=1)},
        {"error": "연결 지연"},
    ):
        assert "<a " not in bridge(**kwargs)


def test_bridge_bounded_deduplicated_and_cleared_on_missing_news():
    items = tuple(replace(ITEM, url=f"https://example.com/{i}") for i in range(50))
    context = MarketContext((FeedState("news_en", items, NOW), FeedState("news_ko", items, NOW)))
    assert news_bridge(context, NOW).count("<a ") == 24
    assert news_bridge(MarketContext(), NOW) == '<div hidden id="btc-news-bridge"></div>'
