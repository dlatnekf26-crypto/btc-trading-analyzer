"""Catalog integrity and quote progress when background providers stall."""

from threading import Event

from btc_analyzer.assets import STOCK_MARKETS, EXCHANGE_HISTORY, MARKETS
from btc_analyzer.data.market_context import MarketContextService


def test_stock_catalog_has_unique_identifiers_and_correct_market_currency():
    assert len(STOCK_MARKETS) == 80
    assert sum(EXCHANGE_HISTORY[c].calendar == "KRX" for c in STOCK_MARKETS) == 40
    assert sum(EXCHANGE_HISTORY[c].calendar == "NYSE" for c in STOCK_MARKETS) == 40
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


def test_collapsed_catalog_has_own_worker_without_increasing_quote_worker_budget():
    release, primary_done = Event(), Event()

    def fetch(key, now):
        if key == "samsung":
            primary_done.set()
        else:
            release.wait(5)
        return ()

    service = MarketContextService(fetch)
    try:
        assert service._executor._max_workers + service._background_executor._max_workers == 4
        assert "samsung" not in service._background_keys
        assert "amore" in service._background_keys
        service.snapshot()
        assert primary_done.wait(2)
    finally:
        release.set()
        service.close()


def test_expanded_markets_have_calendar_and_coin_cap_mapping():
    from btc_analyzer.assets import ASSETS, COIN_IDS, SESSION_MARKETS, INDEX_MARKETS, MACRO_MARKETS
    from btc_analyzer.data.exchange_history import calendar_bars

    assert len(ASSETS) == 16 and set(COIN_IDS.values()) == set(ASSETS)
    assert len(INDEX_MARKETS) == 8 and len(MACRO_MARKETS) == 7
    assert set(EXCHANGE_HISTORY) == set(SESSION_MARKETS)
    for code in ("KOSDAQ", "DOW", "RUSSELL", "NASDAQ", "SILVER", "COPPER", "NATGAS"):
        starts, ends = calendar_bars("2026-10-05", "2026-10-09", "1d", code)
        assert len(starts) and len(starts) == len(ends) and (ends > starts).all()
