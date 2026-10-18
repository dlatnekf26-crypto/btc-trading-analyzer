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
from urllib.parse import unquote, urlsplit, parse_qs
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


@lru_cache(maxsize=8)
def short_fixture_rows(timeframe, boundary):
    import numpy as np

    span = pd.Timedelta(minutes=5 if timeframe == "5m" else 15)
    index = pd.date_range(end=pd.Timestamp(boundary) - span, periods=800, freq=span)
    x = np.arange(len(index))
    close = 90000 * np.exp(0.012 * np.sin(x / 17) + 0.005 * np.cos(x / 7))
    return [
        [int(t.timestamp() * 1000), float(c * 0.999), float(c * 1.003), float(c * 0.997), float(c), 1000.0]
        for t, c in zip(index, close)
    ]


@contextmanager
def offline_market_data(checkout: Path):
    end = pd.Timestamp.now(tz="UTC").floor("h").isoformat()
    rows = fixture_rows(str(checkout.resolve()), end)

    class Client:
        def publicGetKlines(self, params):
            rows = self.fetch_ohlcv(
                params["symbol"].removesuffix("USDT") + "/USDT",
                params["interval"],
                params["startTime"],
                params["limit"],
            )
            return [[*row, row[0], "0", 1, "0", "0", "0"] for row in rows]

        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            scales = {"BTC/USDT": 1, "ETH/USDT": 0.03, "SOL/USDT": 0.0015, "XRP/USDT": 0.000012}
            if symbol not in scales:
                raise AssertionError(f"Unexpected analysis market: {symbol}")
            scale = scales[symbol]
            selected_rows = (
                rows[timeframe]
                if timeframe not in ("5m", "15m")
                else short_fixture_rows(
                    timeframe,
                    pd.Timestamp.now(tz="UTC").floor("5min" if timeframe == "5m" else "15min").isoformat(),
                )
            )
            return [
                [row[0], *[value * scale for value in row[1:5]], row[5]]
                for row in selected_rows
                if row[0] >= since
            ][:limit]

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
        if host == "farside.co.uk":
            funds = (
                ("IBIT", "FBTC")
                if "bitcoin" in url
                else ("BSOL", "VSOL")
                if "/sol/" in url
                else ("ETHA", "FETH")
            )
            rows = []
            for i in reversed(range(10)):
                at = (now - timedelta(days=i)).strftime("%d %b %Y")
                rows.append(f"<tr><td>{at}</td><td>{20 - i}.0</td><td>(5.0)</td><td>{15 - i}.0</td></tr>")
            table = (
                f"<table><tr><th>Date</th><th>{funds[0]}</th><th>{funds[1]}</th><th>Total</th></tr>"
                + "".join(rows)
                + "</table>"
            )
            return Response(table.encode())
        if host == "api.alternative.me":
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            body = {
                "name": "Fear and Greed Index",
                "metadata": {"error": None},
                "data": [
                    {
                        "value": str(32 + i % 8),
                        "value_classification": "Fear",
                        "timestamp": str(int((today - timedelta(days=i)).timestamp())),
                        **(
                            {"time_until_update": str(int((today + timedelta(days=1) - now).total_seconds()))}
                            if i == 0
                            else {}
                        ),
                    }
                    for i in range(30)
                ],
            }
            return Response(json.dumps(body).encode())
        if host == "nfs.faireconomy.media":
            events = [
                {
                    "title": title,
                    "country": "USD",
                    "date": (now + timedelta(days=days)).isoformat(),
                    "impact": "High",
                    "forecast": forecast,
                    "previous": previous,
                }
                for title, days, forecast, previous in (
                    ("Core CPI m/m", 2, "0.3%", "0.2%"),
                    ("Non-Farm Employment Change", 4, "150K", "120K"),
                    ("FOMC Statement", 6, "", ""),
                )
            ]
            return Response(json.dumps(events).encode())
        if host == "query1.finance.yahoo.com":
            symbol = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            interval = parse_qs(urlsplit(url).query).get("interval", ["1m"])[0]
            if symbol in ("NQ=F", "^KS11") and interval in ("5m", "15m", "1d", "1h"):
                import numpy as np
                from btc_analyzer.data.exchange_history import calendar_bars

                starts, ends = calendar_bars(
                    str((now - timedelta(days=14)).date())
                    if interval in ("5m", "15m")
                    else 2000
                    if interval == "1d"
                    else now.year - 1,
                    str((now + timedelta(days=1)).date()) if interval in ("5m", "15m") else now.year + 1,
                    interval,
                    "KOSPI" if symbol == "^KS11" else "NQ",
                )
                starts = starts[ends <= now][-6600 if interval == "1d" else -3500 :]
                x = np.arange(len(starts))
                close = np.exp(0.00007 * x + 0.045 * np.sin(x / 43) + 0.015 * np.cos(x / 11))
                close *= (2800 if symbol == "^KS11" else 22345.5) / close[-1]
                candles = {
                    "open": (close * 0.999).tolist(),
                    "high": (close * 1.008).tolist(),
                    "low": (close * 0.992).tolist(),
                    "close": close.tolist(),
                    "volume": (100000 + 10000 * np.cos(x / 5)).tolist(),
                }
                body = {
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "symbol": symbol,
                                    "instrumentType": "INDEX" if symbol == "^KS11" else "FUTURE",
                                    "currency": "KRW" if symbol == "^KS11" else "USD",
                                    "exchangeTimezoneName": "Asia/Seoul"
                                    if symbol == "^KS11"
                                    else "America/New_York",
                                    "dataGranularity": interval,
                                },
                                "timestamp": (starts.asi8 // 1_000_000_000).tolist(),
                                "indicators": {"quote": [candles]},
                            }
                        ]
                    }
                }
                return Response(json.dumps(body).encode())
            price = {
                "^KS11": 2800.0,
                "NQ=F": 22345.50,
                "CL=F": 87.42,
                "^TNX": 4.25,
                "^TYX": 4.80,
                "KRW=X": 1345.5,
            }[symbol]
            stamp = int(
                (now - timedelta(seconds=2) if symbol == "KRW=X" else now - timedelta(minutes=15)).timestamp()
            )
            body = {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": symbol,
                                "instrumentType": {
                                    "NQ=F": "FUTURE",
                                    "CL=F": "FUTURE",
                                    "^KS11": "INDEX",
                                    "^TNX": "INDEX",
                                    "^TYX": "INDEX",
                                    "KRW=X": "CURRENCY",
                                }[symbol],
                                "currency": "KRW" if symbol in ("KRW=X", "^KS11") else "USD",
                                "exchangeTimezoneName": "Asia/Seoul"
                                if symbol == "^KS11"
                                else "America/New_York",
                                "regularMarketPrice": price,
                                "regularMarketTime": stamp,
                                "chartPreviousClose": price * 0.99,
                                "exchangeDataDelayedBy": 0 if symbol == "KRW=X" else 15,
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
                "비트코인 시장, 유가 급등에 물가 부담",
                "비트코인 시장 주목, 중동 휴전 합의 체결",
                "비트코인, 미국 CPI 발표 예정 앞두고 결과 대기",
                "연준 금리 인하 발표, 비트코인 시장 주목",
                "국제 유가 급등, 공급 부족 우려",
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
        correction = sys.modules.get("btc_analyzer.ui.correction_view")
        if correction is not None:
            correction.calendar_service.clear()


def analysis_app(path, *, default_timeout=30):
    """Open the public analysis deep link rather than the quote-only landing page."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(path, default_timeout=default_timeout)
    app.query_params.update({"market": "BTC", "view": "chart"})
    return app
