"""Confirmed US pre/post-market prices, kept separate from regular-session bars."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class ExtendedQuote:
    price: float
    as_of: datetime
    session: str
    source: str = "Yahoo Finance"


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
        numbers = (price, stamp)
        if not all(
            isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in numbers
        ):
            return
        if price <= 0 or not regular_at.timestamp() < stamp <= now.timestamp():
            return
        intervals = [periods.get(session) or {}]
        historical = meta.get("tradingPeriods") or {}
        if isinstance(historical, dict):
            for day in historical.get(session, [])[:16]:
                if isinstance(day, list):
                    intervals.extend(p for p in day[:4] if isinstance(p, dict))
        for period in intervals:
            start, end = period.get("start"), period.get("end")
            if not all(
                isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                for n in (start, end)
            ):
                continue
            if 0 < end - start <= 86400 and start <= stamp < end:
                candidates.append(
                    ExtendedQuote(float(price), datetime.fromtimestamp(stamp, timezone.utc), session)
                )
                return

    for session in ("pre", "post"):
        stem = "preMarket" if session == "pre" else "postMarket"
        add(meta.get(stem + "Price"), meta.get(stem + "Time"), session)
    if meta.get("dataGranularity") in ("1m", "2m", "5m", "15m"):
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
        for stamp, price in reversed(list(zip(result.get("timestamp") or [], closes))):
            before = len(candidates)
            for session in ("pre", "post"):
                add(price, stamp, session)
            if len(candidates) > before:
                break
    return max(candidates, key=lambda quote: quote.as_of, default=None)
