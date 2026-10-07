"""Strict parsing of Alternative.me's public, daily Crypto Fear & Greed Index."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

UTC = timezone.utc
FEAR_REFRESH_SECONDS = 60
FEAR_SOURCE = "https://alternative.me/crypto/fear-and-greed-index/"
FEAR_API = "https://api.alternative.me/fng/?limit=30&format=json"
LEVELS = {
    "Extreme Fear": ("극단적 공포", "fear"),
    "Fear": ("공포", "fear"),
    "Neutral": ("중립", "neutral"),
    "Greed": ("탐욕", "greed"),
    "Extreme Greed": ("극단적 탐욕", "greed"),
}


@dataclass(frozen=True)
class FearPoint:
    timestamp: datetime
    value: int
    classification: str


@dataclass(frozen=True)
class FearGreed:
    history: tuple[FearPoint, ...]
    fetched_at: datetime
    next_update: datetime | None

    @property
    def latest(self):
        return self.history[-1]

    @property
    def daily_change(self):
        if len(self.history) < 2:
            return None
        latest, previous = self.history[-1], self.history[-2]
        if latest.timestamp.date() - previous.timestamp.date() != timedelta(days=1):
            return None
        return latest.value - previous.value


def _integer(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Invalid daily index number")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]{1,12}", value):
        raise ValueError("Invalid daily index number")
    number = int(value)
    if not 0 <= number <= maximum:
        raise ValueError("Daily index number out of range")
    return number


def parse_fear_greed(payload, now):
    if now.tzinfo is None:
        raise ValueError("A timezone-aware reference time is required")
    now = now.astimezone(UTC)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("metadata", {}), dict)
        or payload.get("metadata", {}).get("error")
    ):
        raise ValueError("Daily index provider error")
    rows = payload.get("data")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 60:
        raise ValueError("Invalid daily index history")
    points, days, update_by_time = [], set(), {}
    for row in rows:
        if not isinstance(row, dict) or row.get("value_classification") not in LEVELS:
            raise ValueError("Unknown daily index classification")
        value = _integer(row.get("value"), 100)
        stamp = datetime.fromtimestamp(_integer(row.get("timestamp"), 10**11), UTC)
        if stamp > now or stamp.date() in days:
            raise ValueError("Future or duplicate daily index")
        days.add(stamp.date())
        if now - stamp <= timedelta(days=31):
            points.append(FearPoint(stamp, value, row["value_classification"]))
            if "time_until_update" in row:
                update_by_time[stamp] = now + timedelta(seconds=_integer(row["time_until_update"], 172800))
    if not points:
        raise ValueError("Daily index history is too old")
    points.sort(key=lambda point: point.timestamp)
    if now - points[-1].timestamp > timedelta(days=7):
        raise ValueError("Latest daily index is too old")
    return FearGreed(tuple(points[-30:]), now, update_by_time.get(points[-1].timestamp))
