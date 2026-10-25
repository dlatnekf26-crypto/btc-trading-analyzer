"""Catalog integrity and quote progress when background providers stall."""

from threading import Event

from btc_analyzer.assets import STOCK_MARKETS, EXCHANGE_HISTORY, MARKETS
from btc_analyzer.data.market_context import MarketContextService


def test_stock_catalog_has_unique_identifiers_and_correct_market_currency():
    assert len(STOCK_MARKETS) == 40
    assert sum(EXCHANGE_HISTORY[c].calendar == "KRX" for c in STOCK_MARKETS) == 20
    assert sum(EXCHANGE_HISTORY[c].calendar == "NYSE" for c in STOCK_MARKETS) == 20
    assert len({a.symbol for a in MARKETS.values()}) == len(MARKETS)
    assert len({a.card_id for a in MARKETS.values()}) == len(MARKETS)
    for code, asset in STOCK_MARKETS.items():
        venue = EXCHANGE_HISTORY[code]
        assert venue.kind == "EQUITY"
        assert (venue.currency, asset.decimals) == (
            ("KRW", 0) if asset.symbol.endswith(".KS") else ("USD", 2)
        )


def test_slow_background_feeds_cannot_block_quote_workers():
    release, quote_done = Event(), Event()
    started = [Event(), Event()]

    def fetch(key, now):
        if key == "amzn":
            assert all(event.wait(2) for event in started)
            quote_done.set()
        else:
            started[("news_ko", "caps").index(key)].set()
            release.wait(5)
        return ()

    service = MarketContextService(fetch, keys=("news_ko", "caps", "amzn"), workers=1)
    try:
        service.snapshot()
        assert all(event.wait(2) for event in started)
        assert quote_done.wait(2), "Quote queued behind blocked background work"
    finally:
        release.set()
        service.close()
