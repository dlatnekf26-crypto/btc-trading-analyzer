"""Past analogues ranked by observed price/volume, never by later returns."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from btc_analyzer.candles import candle_boundary, candle_close, candle_grid
from btc_analyzer.config import COMPOSITE_TIMEFRAMES
from btc_analyzer.data.base_provider import utc

HISTORY_BARS = {"1h": 3000, "4h": 3000, "1d": 3000, "1w": 520, "1M": 120}
WINDOW_OPTIONS = {
    "1h": (24, 48, 72),
    "4h": (21, 42, 84),
    "1d": (14, 30, 60),
    "1w": (8, 12, 24),
    "1M": (6, 12, 18),
}
FORWARD_OPTIONS = {
    "1h": (24, 72, 168),
    "4h": (6, 42, 180),
    "1d": (7, 30, 90),
    "1w": (4, 13, 26),
    "1M": (1, 3, 6),
}


@dataclass(frozen=True)
class HistoricalMatch:
    start: pd.Timestamp
    end: pd.Timestamp
    observed_until: pd.Timestamp
    similarity: float
    price_similarity: float
    volatility_similarity: float
    volume_similarity: float | None
    path: tuple[float, ...]
    forward_return: float
    lowest_return: float
    highest_return: float


@dataclass(frozen=True)
class SimilarityReport:
    timeframe: str
    window: int
    forward: int
    history_start: pd.Timestamp
    history_end: pd.Timestamp
    query_start: pd.Timestamp
    query_end: pd.Timestamp
    current_path: tuple[float, ...]
    candidate_count: int
    best_similarity: float | None
    volume_used: bool
    matches: tuple[HistoricalMatch, ...]


def find_similar_history(
    raw: pd.DataFrame,
    timeframe: str,
    as_of: object,
    window: int = 30,
    forward: int = 30,
    *,
    max_matches: int = 5,
    min_similarity: float = 60,
) -> SimilarityReport:
    """Compare contiguous closed windows; all outcomes end before the query.

    Each score is exp(-distance)*100. Weights: price path 65%, realized
    volatility 20%, relative volume 15%. With no query volume, the first two
    weights are renormalized. This descriptive score is not a probability.
    Selected windows AND their follow-up periods may not overlap each other.
    """
    if timeframe not in COMPOSITE_TIMEFRAMES:
        raise ValueError("지원하는 비교 시간대를 선택하세요.")
    if not (
        isinstance(window, int) and 6 <= window <= 120 and isinstance(forward, int) and 1 <= forward <= 720
    ):
        raise ValueError("비교 구간은 6~120봉, 이후 관찰은 1~720봉이어야 합니다.")
    if (
        not isinstance(max_matches, int)
        or not 1 <= max_matches <= 10
        or not np.isfinite(min_similarity)
        or not 0 <= min_similarity <= 100
    ):
        raise ValueError("유사 구간 개수 또는 최소 유사도가 유효하지 않습니다.")
    if not isinstance(raw.index, pd.DatetimeIndex):
        raise ValueError("시간 정보가 있는 과거 데이터가 필요합니다.")
    columns = ["open", "high", "low", "close", "volume"]
    if not set(columns).issubset(raw.columns):
        raise ValueError("가격과 거래량 데이터가 필요합니다.")
    boundary = candle_boundary(utc(as_of), timeframe)
    frame = raw[columns].copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.loc[frame.index.notna() & (candle_close(frame.index, timeframe) <= boundary)]
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index().tail(HISTORY_BARS[timeframe])
    frame = frame.apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(frame).all(axis=1) & (frame[columns[:4]] > 0).all(axis=1) & (frame.volume >= 0)
    valid &= frame.high >= frame[["open", "close", "low"]].max(axis=1)
    valid &= frame.low <= frame[["open", "close", "high"]].min(axis=1)
    valid &= candle_grid(frame.index.to_series(), timeframe)
    frame = frame.loc[valid]
    if len(frame) < window:
        raise ValueError(f"최근 비교에 필요한 연속 확정 봉 {window}개가 부족합니다.")
    if candle_close(frame.index[-1], timeframe) != boundary:
        raise ValueError("최신 확정 봉이 아직 도착하지 않았습니다. 데이터 갱신 후 다시 비교하세요.")
    # Gap checking uses actual next boundaries, including leap months/weeks.
    breaks = np.r_[0, (frame.index[1:] != candle_close(frame.index[:-1], timeframe)).astype(int)]
    gaps = np.cumsum(breaks)
    query_start = len(frame) - window
    if gaps[-1] != gaps[query_start]:
        raise ValueError("최근 비교 구간에 빠진 봉이 있습니다. 누락된 가격은 채워 넣지 않습니다.")
    close = frame.close.to_numpy()
    volume = frame.volume.to_numpy()
    paths = sliding_window_view(np.log(close), window)
    paths = paths - paths[:, :1]
    query = paths[-1]
    # A small common floor makes flat prices finite, without a fake correlation.
    scale = np.maximum(np.sqrt(np.mean(paths**2, axis=1)), max(np.sqrt(np.mean(query**2)), 0.005))
    price_scores = 100 * np.exp(-np.sqrt(np.mean((paths - query) ** 2, axis=1)) / scale)
    volatility = np.maximum(np.std(np.diff(paths, axis=1), axis=1), 1e-6)
    volatility_scores = 100 * np.exp(-np.abs(np.log(volatility / volatility[-1])))
    volumes = sliding_window_view(volume, window)
    means = volumes.mean(axis=1)
    volume_used = bool(means[-1] > 0)
    if volume_used:
        profiles = np.log1p(volumes / np.maximum(means[:, None], 1e-12))
        volume_scores = 100 * np.exp(-np.sqrt(np.mean((profiles - profiles[-1]) ** 2, axis=1)))
        volume_scores[means <= 0] = 0
        scores = 0.65 * price_scores + 0.20 * volatility_scores + 0.15 * volume_scores
    else:
        volume_scores = None
        scores = (0.65 * price_scores + 0.20 * volatility_scores) / 0.85
    # Future outcomes are not read until after the similarity ranking.
    starts = np.arange(max(0, query_start - window - forward + 1))
    ends = starts + window - 1
    eligible = gaps[ends + forward] == gaps[starts]
    starts, ends = starts[eligible], ends[eligible]
    ranked = starts[np.argsort(-scores[starts], kind="stable")]
    selected = []
    intervals = []
    for start in ranked:
        if scores[start] < min_similarity:
            break
        end = int(start + window - 1)
        observed_end = end + forward
        if any(start <= right and observed_end >= left for left, right in intervals):
            continue
        intervals.append((int(start), observed_end))
        anchor = close[end]
        after = frame.iloc[end + 1 : observed_end + 1]
        selected.append(
            HistoricalMatch(
                start=frame.index[start],
                end=frame.index[end],
                observed_until=candle_close(frame.index[observed_end], timeframe),
                similarity=float(scores[start]),
                price_similarity=float(price_scores[start]),
                volatility_similarity=float(volatility_scores[start]),
                volume_similarity=float(volume_scores[start]) if volume_used else None,
                path=tuple((close[start : observed_end + 1] / anchor * 100).tolist()),
                forward_return=float(close[observed_end] / anchor - 1),
                lowest_return=float(min(0, after.low.min() / anchor - 1)),
                highest_return=float(max(0, after.high.max() / anchor - 1)),
            )
        )
        if len(selected) == max_matches:
            break
    return SimilarityReport(
        timeframe,
        window,
        forward,
        frame.index[0],
        candle_close(frame.index[-1], timeframe),
        frame.index[query_start],
        candle_close(frame.index[-1], timeframe),
        tuple((close[-window:] / close[-1] * 100).tolist()),
        len(starts),
        float(scores[ranked[0]]) if len(ranked) else None,
        volume_used,
        tuple(selected),
    )
