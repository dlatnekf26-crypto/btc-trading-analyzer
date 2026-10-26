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
    periods = periods if isinstance(periods, dict) else {}
    historical = meta.get("tradingPeriods") or {}
    historical = historical if isinstance(historical, dict) else {}
    regular_stamp, now_stamp = regular_at.timestamp(), now.timestamp()
    sessions = {}
    for session in ("pre", "post"):
        intervals = [periods.get(session)]
        days = historical.get(session)
        if isinstance(days, list):
            for day in days[:16]:
                if isinstance(day, list):
                    intervals.extend(day[:4])
        valid = []
        for period in intervals:
            if not isinstance(period, dict):
                continue
            start, end = period.get("start"), period.get("end")
            if (
                all(
                    isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                    for n in (start, end)
                )
                and 0 < end - start <= 86400
                and end > regular_stamp
                and start <= now_stamp
            ):
                valid.append((start, end))
        sessions[session] = valid
    if not any(sessions.values()):
        return None
    candidates = []

    def add(price, stamp, session):
        numbers = (price, stamp)
        if not all(
            isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in numbers
        ):
            return
        if price <= 0 or not regular_stamp < stamp <= now_stamp:
            return
        for start, end in sessions[session]:
            if start <= stamp < end:
                candidates.append(
                    ExtendedQuote(float(price), datetime.fromtimestamp(stamp, timezone.utc), session)
                )
                return

    for session in ("pre", "post"):
        stem = "preMarket" if session == "pre" else "postMarket"
        add(meta.get(stem + "Price"), meta.get(stem + "Time"), session)
    if meta.get("dataGranularity") in ("1m", "2m", "5m", "15m"):
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
        stamps = result.get("timestamp") or []
        for i in range(min(len(stamps), len(closes)) - 1, -1, -1):
            stamp, price = stamps[i], closes[i]
            if isinstance(stamp, (int, float)) and stamp <= regular_stamp:
                continue
            before = len(candidates)
            for session in ("pre", "post"):
                add(price, stamp, session)
            if len(candidates) > before:
                break
    return max(candidates, key=lambda quote: quote.as_of, default=None)
