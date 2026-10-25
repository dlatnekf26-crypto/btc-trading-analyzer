"""Small, shared references for stock mood and won-denominated FX cards."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math


UTC = timezone.utc
REFERENCE_KEYS = ("mood_us", "fx_extra", "caps")
CNN_API = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_SOURCE = "https://www.cnn.com/markets/fear-and-greed"
MOOD_LEVELS = {
    "extreme fear": "극단적 공포",
    "fear": "공포",
    "neutral": "중립",
    "greed": "탐욕",
    "extreme greed": "극단적 탐욕",
}


@dataclass(frozen=True)
class StockMood:
    score: float
    as_of: datetime
    classification: str
    source: str
    url: str


@dataclass(frozen=True)
class WonRates:
    yen100: float
    euro: float
    as_of: datetime


def parse_won_rates(payload, now):
    if payload.get("base") != "EUR" or payload.get("amount") != 1:
        raise ValueError("Unexpected FX base")
    stamp = datetime.strptime(payload["date"], "%Y-%m-%d").replace(tzinfo=UTC)
    krw, jpy = (payload["rates"][code] for code in ("KRW", "JPY"))
    if not all(
        isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) and n > 0
        for n in (krw, jpy)
    ):
        raise ValueError("Invalid FX rate")
    if not timedelta(0) <= now - stamp <= timedelta(days=7):
        raise ValueError("Expired FX date")
    return WonRates(100 * krw / jpy, krw, stamp)


def parse_cnn_mood(payload, now):
    row = payload["fear_and_greed"]
    score = row["score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= 100
    ):
        raise ValueError("Invalid CNN score")
    stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or not timedelta(0) <= now - stamp <= timedelta(days=7):
        raise ValueError("Invalid CNN publication date")
    label = MOOD_LEVELS.get(str(row.get("rating", "")).lower().strip())
    if label is None:
        raise ValueError("Unknown CNN rating")
    return StockMood(float(score), stamp, label, "CNN", CNN_SOURCE)


def fetch_reference(key, now):
    import json
    from btc_analyzer.data.market_context import _download

    if key == "caps":
        from btc_analyzer.data.market_caps import fetch_caps

        return fetch_caps(now)
    if key == "fx_extra":
        return parse_won_rates(
            json.loads(_download("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=KRW,JPY")), now
        )
    if key == "mood_us":
        return parse_cnn_mood(json.loads(_download(CNN_API)), now)
    raise ValueError("No verified index source configured")
