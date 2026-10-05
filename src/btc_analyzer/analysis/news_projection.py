"""Explicit, uncalibrated news scenario layered over the causal technical model."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

import numpy as np

from btc_analyzer.analysis.forecast import ForecastReport
from btc_analyzer.data.market_context import MarketContext, TOPICS

NEWS_MODEL_VERSION = "headline-scenario-v1"
FRAME_DAYS = {"1h": 1 / 24, "4h": 1 / 6, "1d": 1, "1w": 7, "1M": 30.4375}


@dataclass(frozen=True)
class NewsEffect:
    topic: str
    direction: int
    strength: float
    explanation: str
    urls: tuple[str, ...]


@dataclass(frozen=True)
class NewsProjection:
    center: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    as_of: datetime
    effects: tuple[NewsEffect, ...]
    shift: float
    reason: str
    version: str = NEWS_MODEL_VERSION


def project_news(result: ForecastReport, context: MarketContext, now: datetime) -> NewsProjection | None:
    if result.prediction is None:
        return None
    prediction = result.prediction
    origin = prediction.dates[0].to_pydatetime()
    fresh_feeds = [
        feed.updated_at
        for feed in context.feeds
        if feed.key.startswith("news")
        and feed.updated_at is not None
        and timedelta(0) <= now - feed.updated_at <= timedelta(minutes=10)
    ]
    observed = max(fresh_feeds) if fresh_feeds else now
    grouped = {}
    for item in context.news(now, fresh_only=True):
        # Current headlines NEVER enter historical validation, or move a past origin.
        age = now - item.published_at
        if origin < item.published_at <= now and timedelta(0) <= age <= timedelta(hours=24):
            grouped.setdefault(item.topic, []).append(item)
    effects, uncertainty, total = [], 0.0, 0.0
    for topic, items in grouped.items():
        signs = {item.direction for item in items if item.direction}
        direction = next(iter(signs)) if len(signs) == 1 else 0
        directional = [item for item in items if item.direction == direction] if direction else items
        strongest = max(directional, key=lambda item: item.published_at)
        strength = min(1.0, math.exp(-(observed - strongest.published_at).total_seconds() / 43200))
        total += direction * strength
        uncertainty += strength * (1 if len(signs) > 1 else max(item.uncertainty for item in items))
        explanation = (
            "상반된 보도: 방향을 중립으로 두고 범위를 넓혀요." if len(signs) > 1 else strongest.explanation
        )
        effects.append(
            NewsEffect(
                TOPICS[topic], direction, strength, explanation, tuple(sorted({item.url for item in items}))
            )
        )
    # Volatility is per-candle log-return sigma. Convert to daily before applying
    # fixed assumptions; cap total headline shift to 4%, never extrapolate news.
    sigma = result.history.volatility / math.sqrt(FRAME_DAYS[result.history.timeframe])
    unit = float(np.clip(sigma * 0.5, 0.0025, 0.015))
    shock = float(np.clip(unit * total, -0.04, 0.04))
    elapsed = np.array([(date.to_pydatetime() - origin).total_seconds() / 86400 for date in prediction.dates])
    ramp = 1 - np.exp(-np.maximum(elapsed, 0) / 3)
    shift = shock * ramp
    width = min(0.03, unit * uncertainty) * ramp
    base = np.asarray(prediction.center)
    center = base * np.exp(shift)
    lower = np.minimum(prediction.lower, np.asarray(prediction.lower) * np.exp(shift - width))
    upper = np.maximum(prediction.upper, np.asarray(prediction.upper) * np.exp(shift + width))
    reason = (
        "확정 봉 이후 24시간 이내 소식에만 제한된 가정을 반영했어요."
        if effects
        else "반영 가능한 새 뉴스가 없어 기본 전망을 유지해요. 이전 봉에 포함된 뉴스·오래된 자료는 추가하지 않습니다."
    )
    return NewsProjection(
        tuple(center),
        tuple(lower),
        tuple(upper),
        observed,
        tuple(effects),
        float(np.expm1(shift[-1])),
        reason,
    )
