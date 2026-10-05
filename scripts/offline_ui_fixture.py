"""Development checks only: inject public OHLCV responses at the CCXT boundary.

The product always uses Live. No environment variable, hidden UI mode or network
failure can enable these fixtures in the application.
"""

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import sys
from unittest.mock import patch

import ccxt
import pandas as pd


@lru_cache(maxsize=1)
def fixture_rows(checkout: str, end: str):
    sys.path.insert(0, checkout)
    from checkout_bootstrap import ensure_checkout

    ensure_checkout(Path(checkout))
    from btc_analyzer.data.service import demo_bundle

    frames = demo_bundle(
        "1d",
        800,
        end=end,
        include_macro=True,
        history_limits={tf: 3000 for tf in ("1h", "4h", "1d", "1w", "1M")},
    )
    return {
        tf: [[int(t.timestamp() * 1000), *row] for t, row in zip(frame.index, frame.to_numpy().tolist())]
        for tf, frame in frames.items()
    }


@contextmanager
def offline_market_data(checkout: Path):
    end = pd.Timestamp.now(tz="UTC").floor("h").isoformat()
    rows = fixture_rows(str(checkout.resolve()), end)

    class Client:
        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            if symbol != "BTC/USDT":
                raise AssertionError(f"Unexpected analysis market: {symbol}")
            return [row for row in rows[timeframe] if row[0] >= since][:limit]

        def fetch_ticker(self, symbol):
            raise AssertionError("Current prices belong to the browser, not the Python analysis")

    # CCXT survives checkout/stale-module recovery; patching DataService alone
    # would disappear when that recovery correctly reloads project modules.
    with patch.object(ccxt, "binance", lambda options: Client()):
        yield
