"""Validated public OHLCV for exchange-session markets, with explicit close times."""

from functools import lru_cache
import json
from urllib.parse import urlencode, quote

import numpy as np
import pandas as pd

from btc_analyzer.assets import SESSION_MARKETS, EXCHANGE_HISTORY
from btc_analyzer.data.market_context import _download
from btc_analyzer.market_clock import session_index

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"


@lru_cache(maxsize=24)
def calendar_bars(start_year, end_year, timeframe, market="NQ"):
    if market == "KOSPI":
        from btc_analyzer.data.kospi import calendar_bars as kospi_bars

        return kospi_bars(start_year, end_year, timeframe)
    if market != "NQ":
        raise ValueError("지원하지 않는 거래 시장입니다.")
    import pandas_market_calendars as calendars

    start = f"{start_year}-01-01" if isinstance(start_year, int) else str(start_year)
    end = f"{end_year}-12-31" if isinstance(end_year, int) else str(end_year)
    schedule = calendars.get_calendar("CME_Equity").schedule(start, end)
    if timeframe in ("5m", "15m", "1h", "4h"):
        starts, ends = [], []
        for row in schedule.itertuples():
            span = pd.Timedelta(minutes={"5m": 5, "15m": 15, "1h": 60, "4h": 60}[timeframe])
            hours = pd.date_range(row.market_open, row.market_close, freq=span, inclusive="left")
            if pd.notna(row.break_start) and row.break_start < row.break_end:
                hours = hours[(hours < row.break_start) | (hours >= row.break_end)]
            starts.extend(hours)
            ends.extend(min(t + span, row.market_close) for t in hours)
        bars = pd.DataFrame({"start": starts, "end": ends})
        if timeframe == "4h":
            bars = bars.groupby(bars.start.dt.floor("4h")).agg(start=("start", "min"), end=("end", "max"))
            bars["start"] = bars.index
    else:
        # Yahoo's daily NQ series publishes US equity trading dates, omitting
        # full equity holidays even when Globex trades a shortened session.
        publication = calendars.get_calendar("NYSE").schedule(start, end)
        published = publication.index[
            publication.market_close.dt.tz_convert("America/New_York").dt.hour == 16
        ]
        schedule = schedule.loc[schedule.index.isin(published)]
        starts = schedule.index.tz_localize("America/New_York").tz_convert("UTC")
        bars = pd.DataFrame({"start": starts, "end": schedule.market_close.to_numpy()}, index=schedule.index)
        if timeframe in ("1w", "1M"):
            groups = schedule.index.to_period("W-SUN" if timeframe == "1w" else "M")
            bars = bars.groupby(groups).agg(start=("start", "min"), end=("end", "max"))
    return pd.DatetimeIndex(bars.start), pd.DatetimeIndex(bars.end)


def trading_dates(origin, timeframe, count, market="NQ"):
    origin = pd.Timestamp(origin)
    years = max(
        2,
        int(np.ceil(count * {"1h": 0.001, "4h": 0.003, "1d": 0.005, "1w": 0.025, "1M": 0.1}[timeframe])) + 1,
    )
    _, ends = calendar_bars(origin.year - 1, origin.year + years, timeframe, market)
    dates = ends[ends >= origin][:count]
    if len(dates) != count:
        raise ValueError("예측 거래 세션이 부족합니다.")
    return tuple(dates)


def horizon_bars(origin, horizon, market="NQ"):
    origin = pd.Timestamp(origin)
    target = origin + (
        pd.Timedelta(weeks={"1w": 1, "2w": 2}[horizon])
        if horizon in ("1w", "2w")
        else pd.DateOffset(months={"1mo": 1, "2mo": 2, "3mo": 3, "6mo": 6}[horizon])
    )
    return sum(origin < at <= target for at in trading_dates(origin, "1d", 150, market))


def parse_history(payload, timeframe, now, market="NQ"):
    asset, venue = SESSION_MARKETS[market], EXCHANGE_HISTORY[market]
    if timeframe not in ("5m", "15m", "1h", "1d"):
        raise ValueError("원자료는 5분/15분/1시간/일봉으로 수집합니다.")
    result = payload.get("chart", {}).get("result")
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("시장 과거 자료를 받지 못했습니다.")
    result = result[0]
    meta = result.get("meta", {})
    if (
        meta.get("symbol") != asset.symbol
        or meta.get("currency") != venue.currency
        or meta.get("exchangeTimezoneName") != venue.timezone
    ):
        raise ValueError(f"{asset.symbol}·{venue.currency}·거래소 시간대가 일치하지 않습니다.")
    if market == "KOSPI" and meta.get("instrumentType") != "INDEX":
        raise ValueError("코스피 종합지수 원자료가 아닙니다.")
    interval = {"1w": "1wk", "1M": "1mo"}.get(timeframe, timeframe)
    if meta.get("dataGranularity") != interval:
        raise ValueError("자료원이 요청한 봉 주기를 변경했습니다.")
    stamps = result.get("timestamp", [])
    if not stamps or len(stamps) > 30_000:
        raise ValueError("선물 봉 개수가 유효하지 않습니다.")
    quote = result["indicators"]["quote"][0]
    index = pd.to_datetime(stamps, unit="s", utc=True)
    frame = pd.DataFrame({key: quote[key] for key in ("open", "high", "low", "close", "volume")}, index=index)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("중복되거나 역순인 선물 봉입니다.")
    valid = (
        np.isfinite(frame).all(axis=1)
        & (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (frame.volume >= 0)
    )
    valid &= frame.high >= frame[["open", "low", "close"]].max(axis=1)
    valid &= frame.low <= frame[["open", "high", "close"]].min(axis=1)
    if market == "KOSPI" and timeframe != "1d":
        # Yahoo sometimes appends a closing-price snapshot with zero volume
        # and identical OHLC. It is a quote, not a complete intraday candle.
        valid &= ~((frame.volume == 0) & (frame.high == frame.low))
    frame = frame.loc[valid]
    if timeframe == "1d" and market == "NQ":
        local = frame.index.tz_convert("America/New_York")
        frame = frame.loc[(local.hour == 0) & (local.minute == 0) & (local.second == 0)]
    if timeframe == "1d" and market == "KOSPI":
        local = frame.index.tz_convert("Asia/Seoul")
        frame = frame.loc[local.hour.isin((9, 10)) & (local.minute == 0) & (local.second == 0)]
        # Yahoo uses 10:00 KST labels on some delayed-opening days. Canonical
        # daily labels identify the trading date; close times stay calendar-based.
        frame.index = frame.index.normalize()
        if frame.index.has_duplicates:
            raise ValueError("중복된 코스피 일봉 날짜입니다.")
    if frame.empty:
        raise ValueError("유효한 시장 봉이 없습니다.")
    calendar_start = (
        str((frame.index[0] - pd.Timedelta(days=2)).date())
        if timeframe in ("5m", "15m")
        else frame.index[0].year
    )
    calendar_end = (
        str((pd.Timestamp(now) + pd.Timedelta(days=14)).date())
        if timeframe in ("5m", "15m")
        else pd.Timestamp(now).year + 1
    )
    starts, ends = calendar_bars(calendar_start, calendar_end, timeframe, market)
    expected = starts[ends <= now]
    frame = frame.loc[frame.index.isin(expected)]
    frame.index.name = "timestamp"
    frame.attrs.update(
        market=market,
        timeframe=timeframe,
        bar_starts=tuple(map(int, starts.asi8)),
        bar_ends=tuple(map(int, ends.asi8)),
        source=f"Yahoo Finance · {venue.source}",
    )
    return frame


def fetch_history(timeframe, now, market="NQ"):
    params = {"interval": timeframe, "range": "1mo" if timeframe in ("5m", "15m") else "6mo"}
    if timeframe == "1d":
        params = {
            "interval": "1d",
            "period1": int(pd.Timestamp("1999-01-01", tz="UTC").timestamp()),
            "period2": int(pd.Timestamp(now).timestamp()),
        }
    body = _download(
        YAHOO_CHART + quote(SESSION_MARKETS[market].symbol, safe="") + "?" + urlencode(params),
        max_bytes=4_000_000,
    )
    return parse_history(json.loads(body), timeframe, now, market)


def aggregate(frame, timeframe, now):
    starts, ends = calendar_bars(
        frame.index[0].year, pd.Timestamp(now).year + 1, timeframe, frame.attrs["market"]
    )
    source_starts = session_index(frame.attrs["bar_starts"])
    source_ends = session_index(frame.attrs["bar_ends"])
    # Assign every expected source candle to its target session bucket. A missing
    # open-market source candle withholds the target; closed sessions are absent.
    buckets = starts.searchsorted(source_starts, side="right") - 1
    inside = (buckets >= 0) & (source_ends <= ends[np.maximum(buckets, 0)])
    expected = pd.Series(buckets[inside]).value_counts()
    groups = starts.searchsorted(frame.index, side="right") - 1
    result = frame.groupby(groups).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    counts = frame.groupby(groups).size()
    good = (counts == expected.reindex(counts.index)) & (counts.index >= 0)
    result = result.loc[good]
    result.index = starts[result.index]
    result = result.loc[result.index.isin(starts[ends <= now])]
    result.attrs = {
        **frame.attrs,
        "timeframe": timeframe,
        "bar_starts": tuple(map(int, starts.asi8)),
        "bar_ends": tuple(map(int, ends.asi8)),
    }
    return result
