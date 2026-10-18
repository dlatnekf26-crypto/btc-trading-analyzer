"""US cash-equity sessions, shared by all Nasdaq symbols (including early closes)."""

from functools import lru_cache
import pandas as pd


@lru_cache(maxsize=24)
def calendar_bars(start_year, end_year, timeframe):
    from btc_analyzer.data.trading_calendar import schedule as calendar_schedule

    start = f"{start_year}-01-01" if isinstance(start_year, int) else str(start_year)
    end = f"{end_year}-12-31" if isinstance(end_year, int) else str(end_year)
    schedule = calendar_schedule("NYSE", start, end)
    if timeframe in ("5m", "15m", "1h", "4h"):
        span = pd.Timedelta(minutes={"5m": 5, "15m": 15, "1h": 60, "4h": 240}[timeframe])
        starts, ends = [], []
        for row in schedule.itertuples():
            hours = pd.date_range(row.market_open, row.market_close, freq=span, inclusive="left")
            starts.extend(hours)
            ends.extend(min(at + span, row.market_close) for at in hours)
        return pd.DatetimeIndex(starts, tz="UTC"), pd.DatetimeIndex(ends, tz="UTC")
    bars = pd.DataFrame(
        {  # Yahoo's daily labels use 09:30 even before the exchange's 1985
            # opening-time change. Session ends still use the actual calendar.
            "start": (
                schedule.index.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
            ).tz_convert("UTC"),
            "end": schedule.market_close.to_numpy(),
        },
        index=schedule.index,
    )
    if timeframe in ("1w", "1M"):
        groups = schedule.index.to_period("W-SUN" if timeframe == "1w" else "M")
        bars = bars.groupby(groups).agg(start=("start", "min"), end=("end", "max"))
    elif timeframe != "1d":
        raise ValueError("지원하지 않는 주식 봉 주기입니다.")
    return pd.DatetimeIndex(bars.start), pd.DatetimeIndex(bars.end)
