"""Cached exchange hours for quote labels and quiet-market refreshes."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from collections import OrderedDict
from threading import RLock
from zoneinfo import ZoneInfo

from btc_analyzer.assets import SESSION_MARKETS, EXCHANGE_HISTORY

VENUES = {asset.symbol: EXCHANGE_HISTORY[code] for code, asset in SESSION_MARKETS.items()}
_ready, _pending, _lock = OrderedDict(), set(), RLock()


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


def _key(symbol, now):
    venue = VENUES.get(symbol)
    return (
        (
            venue.calendar,
            now.astimezone(ZoneInfo(venue.timezone)).date(),
            venue.calendar == "NYSE" and venue.kind == "EQUITY",
        )
        if venue
        else None
    )


def _phase(windows, now):
    for opened, closed, phase in windows:
        if opened <= now < closed:
            return phase, closed
        if now < opened:
            return "closed", opened
    return "unknown", None


def market_hours(symbol, now=None):
    """Build exchange hours on a worker; unknown calendars never hide quotes."""
    now = now or datetime.now(timezone.utc)
    key = _key(symbol, now)
    if key is None:
        return "unknown", None
    try:
        windows = _windows(*key)
        with _lock:
            _ready[key] = windows
            _ready.move_to_end(key)
            while len(_ready) > 16:
                _ready.popitem(last=False)
        return _phase(windows, now)
    except (ValueError, KeyError, IndexError, TypeError, OverflowError):
        pass
    return "unknown", None


def cached_market_hours(symbol, now=None):
    """UI reads never construct a holiday calendar or wait for its construction."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        windows = _ready.get(_key(symbol, now))
    return _phase(windows, now) if windows is not None else ("unknown", None)


def warm_market_hours(symbol, now, executor):
    """Deduplicate calendar jobs on the existing bounded quote executor."""
    key = _key(symbol, now)
    with _lock:
        if key is None or key in _ready or key in _pending:
            return
        _pending.add(key)

    def finished(_future):
        with _lock:
            _pending.discard(key)

    try:
        executor.submit(market_hours, symbol, now).add_done_callback(finished)
    except RuntimeError:  # A released/reloaded service may already be closing.
        finished(None)
