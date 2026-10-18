"""KRX sessions for the KOSPI cash index (Yahoo ^KS11), never KOSPI futures."""

from functools import lru_cache

import pandas as pd

# CSAT trading schedules: open/close both move one hour. In 2017 the
# earthquake postponement left both the original and rescheduled trading days.
# Keep announced exceptional dates explicit; do not guess future CSAT dates.
CSAT_DAYS = """1999-11-17 2000-11-15 2001-11-07 2002-11-06 2003-11-05
2004-11-17 2005-11-23 2006-11-16 2007-11-15 2008-11-13 2009-11-12
2010-11-18 2011-11-10 2012-11-08 2013-11-07 2014-11-13 2015-11-12
2016-11-17 2017-11-16 2017-11-23 2018-11-15 2019-11-14 2020-12-03
2021-11-18 2022-11-17 2023-11-16 2024-11-14 2025-11-13 2026-11-19""".split()


@lru_cache(maxsize=24)
def calendar_bars(start_year, end_year, timeframe):
    from btc_analyzer.data.trading_calendar import schedule as calendar_schedule

    start = pd.Timestamp(f"{start_year}-01-01" if isinstance(start_year, int) else start_year)
    end = pd.Timestamp(f"{end_year}-12-31" if isinstance(end_year, int) else end_year)
    # The mirror calendar retains discontinued lunch-break fields. Request
    # only open/close, and handle special trading hours the mirror omits.
    schedule = calendar_schedule("XKRX", f"{start.year}-01-01", end, ("market_open", "market_close"))
    # XKRX's precomputed table predates the 2026 local election and the
    # restoration of Constitution Day as a public holiday from 2026.
    dates = schedule.index
    extra = (dates == pd.Timestamp("2026-06-03")) | (
        (dates.year >= 2026) & (dates.month == 7) & (dates.day == 17)
    )
    schedule = schedule.loc[~extra]
    first = schedule.groupby(schedule.index.year).head(1).index
    schedule.loc[first, "market_open"] += pd.Timedelta(hours=1)
    special = schedule.index.isin(pd.to_datetime(CSAT_DAYS))
    schedule.loc[special, ["market_open", "market_close"]] += pd.Timedelta(hours=1)
    schedule = schedule.loc[start:end]
    if timeframe in ("5m", "15m", "1h", "4h"):
        span = pd.Timedelta(minutes={"5m": 5, "15m": 15, "1h": 60, "4h": 240}[timeframe])
        starts, ends = [], []
        for row in schedule.itertuples():
            hours = pd.date_range(row.market_open, row.market_close, freq=span, inclusive="left")
            starts.extend(hours)
            ends.extend(min(at + span, row.market_close) for at in hours)
        return pd.DatetimeIndex(starts, tz="UTC"), pd.DatetimeIndex(ends, tz="UTC")
    # Yahoo labels daily KOSPI candles at 09:00 KST even on a delayed opening.
    # Close timestamps still follow actual KRX hours, including CSAT days.
    bars = pd.DataFrame(
        {"start": schedule.index.tz_localize("UTC"), "end": schedule.market_close.to_numpy()},
        index=schedule.index,
    )
    if timeframe in ("1w", "1M"):
        groups = schedule.index.to_period("W-SUN" if timeframe == "1w" else "M")
        bars = bars.groupby(groups).agg(start=("start", "min"), end=("end", "max"))
    elif timeframe != "1d":
        raise ValueError("지원하지 않는 코스피 봉 주기입니다.")
    return pd.DatetimeIndex(bars.start), pd.DatetimeIndex(bars.end)
