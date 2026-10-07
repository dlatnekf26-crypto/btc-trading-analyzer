"""Visible consensus shares the existing calendar and preserves time/units."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from btc_analyzer.data.economic_calendar import parse_calendar
from btc_analyzer.data.market_context import FeedState
from btc_analyzer.ui import correction_view, economic_releases

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def event(title="Core CPI m/m", forecast="0.3%", previous="0.2%", **changes):
    return dict(
        title=title,
        country="USD",
        date="2026-10-07T08:30:00-04:00",
        impact="High",
        forecast=forecast,
        previous=previous,
        **changes,
    )


def test_market_calendar_and_forecast_share_one_resource_and_consensus_is_not_actual():
    assert correction_view.calendar_service is economic_releases.calendar_service
    values = parse_calendar([event(actual="9.9%"), event("Non-Farm Employment Change", "150K", "120K")], NOW)
    html = economic_releases.releases_card(FeedState("calendar", values, NOW), NOW)
    assert "오늘 21:30" in html and "30분 후" in html and "KST" in html
    assert "0.3%" in html and "0.2%" in html and "150K" in html and "120K" in html
    assert "9.9%" not in html and "시장 예상" in html and "이전 발표" in html
    assert "Forex Factory" in html and "실제 발표값과 달라요" in html


def test_missing_consensus_and_failed_stale_or_future_fetch_never_use_prior_as_forecast():
    values = parse_calendar([event(forecast="", previous="4.25%")], NOW)
    feed = FeedState("calendar", values, NOW)
    html = economic_releases.releases_card(feed, NOW)
    assert "시장 예상</small><b>미제공" in html and "이전 발표</small><b>4.25%" in html
    for failed in (
        replace(feed, error="offline"),
        replace(feed, updated_at=NOW - timedelta(hours=3)),
        replace(feed, updated_at=NOW + timedelta(seconds=1)),
    ):
        html = economic_releases.releases_card(failed, NOW)
        assert "조회 지연" in html and "4.25%" not in html
    assert "확인하고" in economic_releases.releases_card(FeedState("calendar", loading=True), NOW)
    assert "예정 주요 발표가 없어요" in economic_releases.releases_card(FeedState("calendar", (), NOW), NOW)


def test_released_events_drop_from_upcoming_and_new_major_jobs_have_distinct_names():
    values = parse_calendar(
        [event("ADP Non-Farm Employment Change", "100K", "90K"), event("JOLTS Job Openings", "7.2M", "7.1M")],
        NOW,
    )
    assert {item.label for item in values} == {"미국 ADP 민간고용", "미국 JOLTS 구인"}
    html = economic_releases.releases_card(FeedState("calendar", values, NOW), NOW + timedelta(minutes=30))
    assert "예정 주요 발표가 없어요" in html and "100K" not in html
