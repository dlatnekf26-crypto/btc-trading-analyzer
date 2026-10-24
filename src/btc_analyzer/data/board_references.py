"""Small, shared references for stock mood and won-denominated FX cards."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

import numpy as np

UTC = timezone.utc
REFERENCE_KEYS = ("mood_us", "mood_kr", "fx_extra")


@dataclass(frozen=True)
class StockMood:
    score: int
    as_of: datetime


@dataclass(frozen=True)
class WonRates:
    yen100: float
    euro: float
    as_of: datetime


def parse_won_rates(payload, now):
    if payload.get("base") != "EUR" or payload.get("amount") != 1:
        raise ValueError("Unexpected FX base")
    stamp = datetime.strptime(payload["date"], "%Y-%m-%d").replace(tzinfo=UTC)
    krw, jpy = (payload["rates"][code] for code in ("KRW", "JPY"))
    if not all(
        isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) and n > 0
        for n in (krw, jpy)
    ):
        raise ValueError("Invalid FX rate")
    if not timedelta(0) <= now - stamp <= timedelta(days=7):
        raise ValueError("Expired FX date")
    return WonRates(100 * krw / jpy, krw, stamp)


def stock_mood(frame):
    """A price-based proxy, not CNN's index or a market breadth measure."""
    close = frame.close.astype(float)
    if len(close) < 126 or not np.isfinite(close).all() or (close <= 0).any():
        raise ValueError("Insufficient stock mood history")
    close = close.tail(252)
    returns = close.pct_change()
    vol = returns.rolling(20).std().dropna()
    last = float(close.iloc[-1])
    spread = float(close.max() - close.min())
    position = 50 if spread == 0 else 100 * (last - close.min()) / spread
    momentum = np.clip(50 + 250 * (last / close.iloc[-21] - 1), 0, 100)
    trend = np.clip(50 + 150 * (last / close.mean() - 1), 0, 100)
    calm = 50 if vol.max() == vol.min() else 100 * float((vol > vol.iloc[-1]).mean())
    score = int(round(float(np.mean([position, momentum, trend, calm]))))
    from btc_analyzer.market_clock import bar_closes

    stamp = bar_closes(frame, frame.index[-1], "1d").to_pydatetime()
    return StockMood(score, stamp)


def fetch_reference(key, now):
    import json
    from btc_analyzer.data.market_context import _download

    if key == "fx_extra":
        return parse_won_rates(
            json.loads(_download("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=KRW,JPY")), now
        )
    from btc_analyzer.assets import MARKETS
    from btc_analyzer.data.exchange_history import parse_history, YAHOO_CHART
    from urllib.parse import quote

    market = {"mood_us": "SP500", "mood_kr": "KOSPI"}[key]
    url = YAHOO_CHART + quote(MARKETS[market].symbol, safe="") + "?interval=1d&range=2y"
    frame = parse_history(json.loads(_download(url)), "1d", now, market)
    result = stock_mood(frame)
    if not timedelta(0) <= now - result.as_of <= timedelta(days=7):
        raise ValueError("Expired stock mood history")
    return result
