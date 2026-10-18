"""Confirmed US pre/post-market prices, kept separate from regular-session bars."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class ExtendedQuote:
    price: float
    as_of: datetime
    session: str


def extended_quote(result, regular_at, now):
    meta = result["meta"]
    # KRX's Yahoo session boundaries can be outdated. Do not classify its
    # closing auction as an after-hours trade, or extend an index artificially.
    if (
        meta.get("instrumentType") != "EQUITY"
        or meta.get("currency") != "USD"
        or meta.get("exchangeTimezoneName") != "America/New_York"
    ):
        return None
    periods = meta.get("currentTradingPeriod") or {}
    candidates = []

    def add(price, stamp, session):
        period = periods.get(session) or {}
        start, end = period.get("start"), period.get("end")
        numbers = (price, stamp, start, end)
        if not all(
            isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in numbers
        ):
            return
        if price <= 0 or not regular_at.timestamp() < stamp <= now.timestamp() or not start <= stamp < end:
            return
        candidates.append(ExtendedQuote(float(price), datetime.fromtimestamp(stamp, timezone.utc), session))

    for session in ("pre", "post"):
        stem = "preMarket" if session == "pre" else "postMarket"
        add(meta.get(stem + "Price"), meta.get(stem + "Time"), session)
    if meta.get("dataGranularity") in ("1m", "2m", "5m", "15m"):
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
        for stamp, price in zip(result.get("timestamp") or [], closes):
            for session in ("pre", "post"):
                add(price, stamp, session)
    return max(candidates, key=lambda quote: quote.as_of, default=None)
