"""Share calendar schedules; holiday cache construction is not thread-safe upstream."""

from functools import lru_cache
from threading import RLock
import warnings

_LOCK = RLock()


@lru_cache(maxsize=32)
def _schedule(name, start, end, market_times):
    import pandas_market_calendars as calendars

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"\['break_start', 'break_end'\] are discontinued")
        calendar = calendars.get_calendar(name)
        kwargs = {"market_times": list(market_times)} if market_times else {}
        return calendar.schedule(start, end, **kwargs)


def schedule(name, start, end, market_times=()):
    # Hold the lock across the cache lookup so concurrent first users build once.
    # Callers can adjust exceptional sessions without mutating the shared cache.
    with _LOCK:
        return _schedule(name, start, end, market_times).copy()
