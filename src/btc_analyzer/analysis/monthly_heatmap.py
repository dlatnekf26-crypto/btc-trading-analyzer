"""Observed monthly Binance returns; complete UTC calendar candles only."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from btc_analyzer.candles import candle_boundary, candle_close


@dataclass(frozen=True)
class MonthlyCell:
    year: int | None
    month: int
    change: float | None
    samples: int
    status: str


@dataclass(frozen=True)
class MonthlyHeatmap:
    years: tuple[int, ...]
    cells: tuple[MonthlyCell, ...]
    averages: tuple[MonthlyCell, ...]
    bars: int


def monthly_heatmap(frame, cutoff, years=0):
    if years not in (0, 5):
        raise ValueError("월별 히트맵은 전체 또는 최근 5년입니다.")
    cutoff = pd.Timestamp(cutoff)
    if cutoff.tzinfo is None:
        raise ValueError("월봉 마감 기준에는 시간대가 필요합니다.")
    cutoff = cutoff.tz_convert("UTC")
    boundary = candle_boundary(cutoff, "1M")
    columns = ["open", "high", "low", "close"]
    data = pd.DataFrame(columns=columns)
    if (
        isinstance(frame, pd.DataFrame)
        and isinstance(frame.index, pd.DatetimeIndex)
        and frame.index.tz is not None
        and set(columns).issubset(frame.columns)
    ):
        data = frame[columns].copy()
        data.index = data.index.tz_convert("UTC")
        data = data.loc[~data.index.duplicated(keep=False)].sort_index()
        data = data.apply(pd.to_numeric, errors="coerce")
        values = data.to_numpy(dtype=float)
        valid = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
        valid &= data.high.ge(data[["open", "close", "low"]].max(axis=1)).to_numpy()
        valid &= data.low.le(data[["open", "close", "high"]].min(axis=1)).to_numpy()
        grid = (data.index.day == 1) & (data.index == data.index.normalize())
        data = data.loc[valid & grid & (candle_close(data.index, "1M") <= cutoff)]
    # Bound the rendered history to Binance's actual launch era, not invented years.
    if not data.empty:
        data = data.loc[data.index >= pd.Timestamp("2017-08-01", tz="UTC")]
    first = int(data.index[0].year) if not data.empty else cutoff.year
    if years:
        first = max(first, cutoff.year - years + 1)
        if not data.empty:
            data = data.loc[data.index.year >= first]
    shown = tuple(range(cutoff.year, first - 1, -1))
    returns = {(stamp.year, stamp.month): float(row.close / row.open - 1) for stamp, row in data.iterrows()}
    cells = []
    for year in shown:
        for month in range(1, 13):
            value = returns.get((year, month))
            stamp = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
            status = (
                "partial"
                if value is not None and (year, month) == (2017, 8)
                else "closed"
                if value is not None
                else "open"
                if stamp == boundary
                else "missing"
            )
            cells.append(MonthlyCell(year, month, value, int(value is not None), status))
    averages = []
    for month in range(1, 13):
        values = [
            value
            for (year, number), value in returns.items()
            if number == month and year in shown and (year, number) != (2017, 8)
        ]
        averages.append(
            MonthlyCell(None, month, float(np.mean(values)) if values else None, len(values), "average")
        )
    return MonthlyHeatmap(shown, tuple(cells), tuple(averages), len(data))
