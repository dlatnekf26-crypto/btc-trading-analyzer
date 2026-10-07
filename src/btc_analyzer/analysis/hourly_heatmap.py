"""Observed KST weekday/4-hour returns, using only complete closed blocks."""

from dataclasses import dataclass

import pandas as pd

from btc_analyzer.analysis.session_patterns import HOUR, closed_hours

WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
MIN_BLOCKS = 2


@dataclass(frozen=True)
class HeatmapCell:
    weekday: int
    hour: int
    samples: int
    median_return: float | None


@dataclass(frozen=True)
class HourlyHeatmap:
    days: int
    bars: int
    blocks: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    cells: tuple[HeatmapCell, ...]


def hourly_heatmap(frame, cutoff, days=30):
    if days not in (14, 30):
        raise ValueError("히트맵 관측 기간은 14일 또는 30일입니다.")
    data = closed_hours(frame, cutoff)
    cutoff = pd.Timestamp(cutoff)
    if not data.empty:
        data = data.loc[data.index >= cutoff.tz_convert("UTC").floor("h") - pd.Timedelta(days=days)]
    grouped = {}
    blocks = 0
    if not data.empty:
        local = data.index.tz_convert("Asia/Seoul")
        buckets = local.floor("4h")
        aggregate = data.groupby(buckets).agg(
            first_open=("open", "first"), last_close=("close", "last"), bars=("close", "size")
        )
        # Four unique grid-aligned bars in this bucket are all required.
        complete = aggregate.loc[aggregate.bars == 4]
        blocks = len(complete)
        if blocks:
            summary = pd.DataFrame(
                {
                    "weekday": complete.index.weekday,
                    "hour": complete.index.hour,
                    "change": (complete.last_close / complete.first_open - 1).to_numpy(),
                }
            )
            stats = summary.groupby(["weekday", "hour"]).change.agg(["size", "median"])
            grouped = {
                (weekday, hour): (int(row["size"]), float(row["median"]))
                for (weekday, hour), row in stats.iterrows()
            }
    cells = []
    for weekday in range(7):
        for hour in range(0, 24, 4):
            samples, median = grouped.get((weekday, hour), (0, None))
            cells.append(HeatmapCell(weekday, hour, samples, median if samples >= MIN_BLOCKS else None))
    return HourlyHeatmap(
        days,
        len(data),
        blocks,
        data.index[0] if not data.empty else None,
        data.index[-1] + HOUR if not data.empty else None,
        tuple(cells),
    )
