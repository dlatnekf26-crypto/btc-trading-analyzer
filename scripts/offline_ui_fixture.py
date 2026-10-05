"""Development checks only: inject public OHLCV responses at the CCXT boundary.

The product always uses Live. No environment variable, hidden UI mode or network
failure can enable these fixtures in the application.
"""

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import sys
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape

import ccxt
import pandas as pd
import requests


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
    with patch.object(ccxt, "binance", lambda options: Client()), offline_context_data():
        yield


@contextmanager
def offline_context_data():
    """Mock only the new HTTP provider boundary, even across checkout recovery."""
    actual_get = requests.get

    class Response:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield self.body

    def get(url, **kwargs):
        host = urlsplit(url).hostname
        now = datetime.now(timezone.utc)
        if host == "query1.finance.yahoo.com":
            symbol = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            price = 22345.50 if symbol == "NQ=F" else 4.25
            stamp = int((now - timedelta(minutes=15)).timestamp())
            body = {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": symbol,
                                "instrumentType": "FUTURE" if symbol == "NQ=F" else "INDEX",
                                "regularMarketPrice": price,
                                "regularMarketTime": stamp,
                                "chartPreviousClose": price * 0.99,
                                "exchangeDataDelayedBy": 15,
                            },
                            "timestamp": [stamp - 300 * i for i in reversed(range(60))],
                            "indicators": {
                                "quote": [{"close": [price * (0.99 + i / 6000) for i in range(60)]}]
                            },
                        }
                    ]
                }
            }
            return Response(json.dumps(body).encode())
        if host == "news.google.com":
            titles = (
                "유가 급등, 공급 우려 지속",
                "중동 휴전 합의 체결",
                "미국 CPI 발표 예정, 결과 대기",
                "연준 금리 인하 발표",
            )
            nodes = []
            for i, title in enumerate(titles):
                published = format_datetime(now - timedelta(minutes=10 + i), usegmt=True)
                nodes.append(
                    f"<item><title>{escape(title)} - Fixture News</title><link>https://news.google.com/rss/articles/fixture{i}</link><source>Fixture News</source><pubDate>{published}</pubDate></item>"
                )
            return Response(("<rss><channel>" + "".join(nodes) + "</channel></rss>").encode())
        return actual_get(url, **kwargs)

    with patch.object(requests, "get", get):
        yield
        module = sys.modules.get("btc_analyzer.ui.market_context")
        if module is not None:
            module.cached_context_service.clear()
