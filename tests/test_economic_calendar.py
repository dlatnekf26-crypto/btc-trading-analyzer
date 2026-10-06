"""Calendar dates/consensus cannot become invented results or directional news."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from threading import Event
import time

import pytest
import requests

from btc_analyzer.data.economic_calendar import (
    CALENDAR_REFRESH,
    parse_calendar,
    fetch_calendar,
    upcoming_events,
    release_condition,
)
from btc_analyzer.data.market_context import FeedState, MarketContextService

NOW = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)


def release(**changes):
    return {
        "title": "Core CPI m/m",
        "country": "USD",
        "date": "2026-10-08T08:30:00-04:00",
        "impact": "High",
        "forecast": "0.3%",
        "previous": "0.2%",
        **changes,
    }


def test_provider_offset_consensus_previous_and_missing_results_remain_distinct():
    values = parse_calendar([release(actual="9.9%")], NOW)
    event = values[0]
    assert event.at == datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
    assert event.forecast == "0.3%" and event.previous == "0.2%"
    assert "근원" in event.label and "전월비" in event.label
    assert not hasattr(event, "actual")
    assert "높아" in release_condition(event)
    assert parse_calendar([release(forecast="", previous="1.2%")], NOW)[0].forecast is None


@pytest.mark.parametrize(
    "changes",
    [
        {"country": "EUR"},
        {"title": "Crude Oil Inventories"},
        {"impact": "Low"},
        {"date": "2026-10-08"},
        {"date": "Tentative"},
        {"date": "2026-10-08T08:30:00"},
        {"date": "2027-10-08T08:30:00Z"},
        {"date": None},
    ],
)
def test_unrelated_unscheduled_and_out_of_range_rows_are_not_release_predictions(changes):
    assert parse_calendar([release(**changes)], NOW) == ()


def test_only_current_consensus_can_drive_a_future_scenario():
    event = parse_calendar([release()], NOW)[0]
    feed = FeedState("calendar", (event,), NOW)
    assert upcoming_events(feed, NOW) == (event,)
    assert upcoming_events(replace(feed, error="source unavailable"), NOW) == ()
    assert upcoming_events(replace(feed, updated_at=NOW - timedelta(hours=3)), NOW) == ()
    assert upcoming_events(replace(feed, updated_at=NOW + timedelta(seconds=1)), NOW) == ()
    assert upcoming_events(feed, event.at) == ()
    assert upcoming_events(feed, NOW, NOW + timedelta(hours=1)) == ()


def test_duplicates_malformed_values_and_rate_ranges():
    event = parse_calendar([release(), release(), release(forecast="<script>")], NOW)
    assert len(event) == 1
    assert parse_calendar([release(forecast="4.25%-4.50%")], NOW)[0].forecast == "4.25%-4.50%"
    assert parse_calendar([release(forecast="nan")], NOW)[0].forecast is None
    with pytest.raises(ValueError):
        parse_calendar({"data": [release()]}, NOW)


def test_actual_provider_parser_uses_bounded_downloader(monkeypatch):
    from btc_analyzer.data import market_context

    calls = []
    monkeypatch.setattr(
        market_context, "_download", lambda url: calls.append(url) or json.dumps([release()]).encode()
    )
    assert fetch_calendar("calendar", NOW)[0].forecast == "0.3%"
    assert calls == ["https://nfs.faireconomy.media/ff_calendar_thisweek.json"]


def test_calendar_is_nonblocking_single_inflight_and_refreshes_no_more_than_twice_hourly():
    clock, calls = [NOW], []
    release_request = Event()

    def fetch(key, now):
        calls.append(now)
        assert release_request.wait(2)
        if len(calls) > 1:
            raise requests.ConnectionError("offline")
        return parse_calendar([release()], now)

    service = MarketContextService(
        fetch,
        lambda: clock[0],
        keys=("calendar",),
        refresh_intervals={"calendar": CALENDAR_REFRESH},
        workers=1,
    )
    try:
        started = time.monotonic()
        for _ in range(20):
            service.snapshot()
        assert time.monotonic() - started < 0.2
        release_request.set()
        for _ in range(200):
            first = service.snapshot().feed("calendar")
            if not first.loading:
                break
            time.sleep(0.005)
        assert first.value and len(calls) == 1
        clock[0] += timedelta(seconds=1799)
        service.snapshot()
        assert len(calls) == 1
        clock[0] += timedelta(seconds=2)
        for _ in range(200):
            failed = service.snapshot().feed("calendar")
            if not failed.loading:
                break
            time.sleep(0.005)
        assert failed.error and failed.value == first.value
        assert upcoming_events(failed, clock[0]) == ()
        clock[0] += timedelta(seconds=60)
        service.snapshot()
        assert len(calls) == 2
    finally:
        release_request.set()
        service.close()
