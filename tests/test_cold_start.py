"""Keep quote-board startup independent of analysis and hidden stock queues."""

from pathlib import Path
import subprocess
import sys
from threading import Event

from btc_analyzer.data.market_context import MarketContextService, SYMBOLS


def test_board_imports_do_not_initialize_analysis_engines():
    program = """
import streamlit, sys
import btc_analyzer.ui.presentation
import btc_analyzer.ui.live_prices
import btc_analyzer.ui.market_board
assert 'btc_analyzer.strategy.composite' not in sys.modules
assert 'btc_analyzer.ui.live_analysis' not in sys.modules
assert 'btc_analyzer.ui.analysis_view' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        timeout=20,
    )


def test_cold_quote_queue_serves_visible_countries_before_hidden_stocks():
    started, release = Event(), Event()
    calls = []

    def fetch(key, now):
        if key in SYMBOLS:
            calls.append(key)
            started.set()
            assert release.wait(3)
        return None

    service = MarketContextService(fetcher=fetch, workers=1)
    try:
        snapshot = service.snapshot()
        assert started.wait(1)
        assert calls == ["fx"]  # The snapshot returned while its first request is still blocked.
        assert snapshot.feed("msft").loading
        release.set()
        service._executor.shutdown(wait=True)
        assert len(calls) == len(set(calls)) == len(SYMBOLS)
        assert calls.index("msft") < calls.index("lges")
        assert calls.index("hyundai") < calls.index("aapl")
        assert calls.index("nq") < calls.index("lges")
    finally:
        release.set()
        service.close()
