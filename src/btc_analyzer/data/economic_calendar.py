"""Public weekly release schedule and consensus; never fabricate actual releases."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re

UTC = timezone.utc
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
SOURCE_URL = "https://www.forexfactory.com/calendar"
CALENDAR_REFRESH = 1800
CALENDAR_MAX_AGE = timedelta(hours=2)


@dataclass(frozen=True)
class EconomicEvent:
    title: str
    label: str
    topic: str
    at: datetime
    forecast: str | None
    previous: str | None
    impact: str
    source_url: str = SOURCE_URL

    @property
    def key(self):
        return f"{self.at.isoformat()}|{self.title}"


def event_kind(title):
    title = title.casefold()
    for pattern, label, topic in (
        (r"\bcpi\b", "미국 소비자물가 CPI", "inflation"),
        (r"\bpce\b", "미국 PCE 물가", "inflation"),
        (r"\bppi\b", "미국 생산자물가 PPI", "inflation"),
        (r"federal funds rate", "미국 기준금리", "rates"),
        (r"fomc.*statement", "연준 FOMC 성명", "rates"),
        (r"fomc.*press conference", "연준 FOMC 기자회견", "rates"),
        (r"fomc.*minutes", "연준 FOMC 의사록", "rates"),
        (r"fomc", "연준 FOMC", "rates"),
        (r"adp.*employment", "미국 ADP 민간고용", "jobs"),
        (r"jolts.*job openings", "미국 JOLTS 구인", "jobs"),
        (r"non.?farm.*(?:employment|payroll)", "미국 비농업 고용", "jobs"),
        (r"unemployment rate", "미국 실업률", "jobs"),
        (r"average hourly earnings", "미국 시간당 임금", "jobs"),
        (r"unemployment claims", "미국 실업수당 청구", "jobs"),
        (r"\bgdp\b", "미국 GDP", "growth"),
        (r"ism.*pmi", "미국 ISM 경기지표", "growth"),
        (r"retail sales", "미국 소매판매", "growth"),
        (r"consumer (?:confidence|sentiment)", "미국 소비자심리", "growth"),
    ):
        if re.search(pattern, title):
            if "core" in title and topic == "inflation":
                label = label.replace("미국 ", "미국 근원 ")
            for unit, meaning in (("m/m", "전월비"), ("y/y", "전년비"), ("q/q", "전분기비")):
                if unit in title:
                    label += f" · {meaning}"
                    break
            return label, topic
    return None


def consensus_value(value):
    """Preserve provider units and ranges, without interpreting prior as forecast."""
    if not isinstance(value, str) or len(value) > 32:
        return None
    value = value.strip()
    numeric = r"[+-]?\d[\d,]*(?:\.\d+)?(?:%|[KMBkmb])?"
    return value if re.fullmatch(rf"{numeric}(?:\s*[-–]\s*{numeric})?", value) else None


def parse_calendar(payload, now: datetime) -> tuple[EconomicEvent, ...]:
    if not isinstance(payload, list) or len(payload) > 1000:
        raise ValueError("Invalid calendar payload")
    events = {}
    for row in payload:
        if (
            not isinstance(row, dict)
            or row.get("country") != "USD"
            or row.get("impact") not in ("High", "Medium")
        ):
            continue
        title = row.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            continue
        kind = event_kind(title)
        if kind is None:
            continue
        try:
            at = datetime.fromisoformat(row["date"].replace("Z", "+00:00"))
            if at.tzinfo is None:
                continue  # A date-only, tentative or all-day event has no exact release time.
            at = at.astimezone(UTC)
            if not now - timedelta(days=1) <= at <= now + timedelta(days=14):
                continue
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        label, topic = kind
        event = EconomicEvent(
            title.strip(),
            label,
            topic,
            at,
            consensus_value(row.get("forecast")),
            consensus_value(row.get("previous")),
            row["impact"],
        )
        events.setdefault(event.key, event)
    return tuple(sorted(events.values(), key=lambda event: (event.at, event.title)))


def fetch_calendar(key, now):
    from btc_analyzer.data.market_context import _download

    if key != "calendar":
        raise ValueError("Unknown calendar feed")
    return parse_calendar(json.loads(_download(CALENDAR_URL)), now)


def upcoming_events(feed, now, until=None):
    """A fresh fetch is required before current consensus can affect a scenario."""
    if feed.updated_at is None or not timedelta(0) <= now - feed.updated_at <= CALENDAR_MAX_AGE or feed.error:
        return ()
    return tuple(
        event
        for event in (feed.value or ())
        if isinstance(event, EconomicEvent) and now < event.at and (until is None or event.at <= until)
    )


def release_condition(event):
    reference = f"예상 {event.forecast}" if event.forecast else "시장 예상"
    if event.topic == "inflation":
        return f"{reference}보다 물가가 높아 금리 부담이 커지면 부담, 낮아져 부담이 줄면 우호 시나리오예요."
    if event.topic == "rates":
        return "예상보다 높은 금리·긴축적 발언이면 부담, 완화적 해석이면 우호 시나리오예요."
    if "unemployment" in event.title.casefold():
        return f"{reference}보다 낮은 실업 지표가 금리 부담으로 해석되면 부담이에요. 경기침체 해석이면 반응이 달라져요."
    return f"{reference}보다 강한 수치가 금리 부담으로 해석되면 부담, 연착륙·완화 기대로 해석되면 우호 시나리오예요."
