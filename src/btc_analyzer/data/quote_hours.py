"""Cached exchange hours for quote labels and quiet-market refreshes."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from btc_analyzer.assets import SESSION_MARKETS, EXCHANGE_HISTORY

VENUES = {asset.symbol: EXCHANGE_HISTORY[code] for code, asset in SESSION_MARKETS.items()}


@lru_cache(maxsize=16)
def _windows(calendar, day, extended):
    from btc_analyzer.data.trading_calendar import schedule

    end = day + timedelta(days=14)
    if calendar == "KRX":
        from btc_analyzer.data.kospi import session_schedule

        table = session_schedule(str(day), str(end))
        return tuple(
            (row.market_open.to_pydatetime(), row.market_close.to_pydatetime(), "regular")
            for row in table.itertuples()
        )
    table = schedule(calendar, str(day - timedelta(days=1)), str(end))
    windows = []
    for row in table.itertuples():
        opened, closed = row.market_open.to_pydatetime(), row.market_close.to_pydatetime()
        if calendar == "NYSE":
            if extended:
                pre = opened.astimezone(ZoneInfo("America/New_York")).replace(hour=4, minute=0)
                windows.extend(
                    (
                        (pre, opened, "pre"),
                        (opened, closed, "regular"),
                        (closed, closed + timedelta(hours=4), "post"),
                    )
                )
            else:
                windows.append((opened, closed, "regular"))
        else:
            pause, resume = row.break_start, row.break_end
            if pause < resume:
                windows.extend(
                    ((opened, pause.to_pydatetime(), "regular"), (resume.to_pydatetime(), closed, "regular"))
                )
            else:
                windows.append((opened, closed, "regular"))
    return tuple(windows)


def market_hours(symbol, now=None):
    """Return current phase and next boundary; unknown calendars never hide quotes."""
    venue = VENUES.get(symbol)
    if venue is None:
        return "unknown", None
    now = now or datetime.now(timezone.utc)
    try:
        windows = _windows(
            venue.calendar, now.astimezone(ZoneInfo(venue.timezone)).date(), venue.kind == "EQUITY"
        )
        for opened, closed, phase in windows:
            if opened <= now < closed:
                return phase, closed
            if now < opened:
                return "closed", opened
    except (ValueError, KeyError, IndexError, TypeError, OverflowError):
        pass
    return "unknown", None
