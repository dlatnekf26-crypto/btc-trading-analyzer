"""JPX holidays, lunch break and the November 2024 close-time change."""

from functools import lru_cache
import pandas as pd

from btc_analyzer.data.trading_calendar import schedule


@lru_cache(maxsize=24)
def calendar_bars(start_year, end_year, timeframe):
    start = f"{start_year}-01-01" if isinstance(start_year, int) else str(start_year)
    end = f"{end_year}-12-31" if isinstance(end_year, int) else str(end_year)
    table = schedule("JPX", start, end)
    if timeframe in ("5m", "15m", "1h", "4h"):
        span = pd.Timedelta(minutes={"5m": 5, "15m": 15, "1h": 60, "4h": 240}[timeframe])
        starts, ends = [], []
        for row in table.itertuples():
            for at in pd.date_range(row.market_open, row.market_close, freq=span, inclusive="left"):
                close = min(at + span, row.market_close)
                # Yahoo hourly labels stay on whole hours: the 12:00 label
                # contains trades from the 12:30 afternoon reopening.
                if at >= row.break_start and close <= row.break_end:
                    continue
                starts.append(at)
                ends.append(close)
        return pd.DatetimeIndex(starts, tz="UTC"), pd.DatetimeIndex(ends, tz="UTC")
    bars = pd.DataFrame({"start": table.market_open, "end": table.market_close})
    if timeframe in ("1w", "1M"):
        groups = table.index.to_period("W-SUN" if timeframe == "1w" else "M")
        bars = bars.groupby(groups).agg(start=("start", "min"), end=("end", "max"))
    elif timeframe != "1d":
        raise ValueError("지원하지 않는 일본 지수 봉 주기입니다.")
    return pd.DatetimeIndex(bars.start), pd.DatetimeIndex(bars.end)
