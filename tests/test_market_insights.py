"""Daily sentiment freshness, cache/backoff and complete, causal KST heatmaps."""

from datetime import datetime, timedelta, timezone
from threading import Event
import time

import numpy as np
import pandas as pd
import pytest
import requests

from btc_analyzer.analysis.hourly_heatmap import hourly_heatmap
from btc_analyzer.data.market_context import FeedState, MarketContextService
from btc_analyzer.data.sentiment import parse_fear_greed
from btc_analyzer.ui.market_insights import cached_heatmap, fear_card, heatmap_card

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def payload():
    return {
        "metadata": {"error": None},
        "data": [
            {
                "timestamp": str(int((NOW.replace(hour=0) - timedelta(days=i)).timestamp())),
                "value": str(20 + i),
                "value_classification": "Fear",
                **({"time_until_update": "43200"} if i == 0 else {}),
            }
            for i in range(30)
        ],
    }


def hours():
    index = pd.date_range("2026-09-07", periods=28 * 24, freq="h", tz="Asia/Seoul")
    offset = index.hour % 4
    change = np.where((index.weekday == 0) & (index.hour < 4), 0.04, 0.0)
    opening = 100 * (1 + change * offset / 4)
    closing = 100 * (1 + change * (offset + 1) / 4)
    return pd.DataFrame(
        dict(
            open=opening,
            high=np.maximum(opening, closing) * 1.01,
            low=np.minimum(opening, closing) * 0.99,
            close=closing,
        ),
        index=index.tz_convert("UTC"),
    )


def cutoff(frame):
    return frame.index[-1] + pd.Timedelta(hours=1)


def idle(service):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = service.snapshot()
        if not any(feed.loading for feed in state.feeds):
            return state
        time.sleep(0.005)
    raise AssertionError("Background sentiment request did not finish")


def test_sentiment_is_chronological_daily_data_and_zero_is_a_real_index_value():
    body = payload()
    body["data"].reverse()
    value = parse_fear_greed(body, NOW)
    assert len(value.history) == 30 and value.latest.value == 20 and value.daily_change == -1
    assert value.next_update == NOW + timedelta(hours=12)
    body["data"][-1].update(value="0", value_classification="Extreme Fear")
    zero = parse_fear_greed(body, NOW)
    html = fear_card(FeedState("fear", zero, NOW), NOW)
    assert 'data-score="0"' in html and "극단적 공포" in html and "Alternative.me" in html
    assert "일별 갱신" in html and "실시간" not in html
    body["data"] = body["data"][-1:]
    assert "<circle" in fear_card(FeedState("fear", parse_fear_greed(body, NOW), NOW), NOW)


@pytest.mark.parametrize("bad", [True, -1, 101, "nan", "50.0", None, 50.5])
def test_bad_index_values_are_never_silently_clamped_or_replaced(bad):
    body = payload()
    body["data"][0]["value"] = bad
    with pytest.raises(ValueError):
        parse_fear_greed(body, NOW)


@pytest.mark.parametrize(
    "issue", ["future", "duplicate", "unknown", "error", "metadata", "empty", "oversize"]
)
def test_sentiment_rejects_future_duplicate_error_and_unsafe_classification(issue):
    body = payload()
    if issue == "future":
        body["data"][0]["timestamp"] = str(int(NOW.timestamp()) + 1)
    elif issue == "duplicate":
        body["data"][1]["timestamp"] = body["data"][0]["timestamp"]
    elif issue == "unknown":
        body["data"][0]["value_classification"] = "<script>oops</script>"
    elif issue == "error":
        body["metadata"]["error"] = "provider error"
    elif issue == "metadata":
        body["metadata"] = None
    elif issue == "empty":
        body["data"] = []
    else:
        body["data"] *= 3
    with pytest.raises(ValueError):
        parse_fear_greed(body, NOW)


def test_missing_yesterday_is_not_an_invented_daily_change_and_old_index_is_last_value():
    body = payload()
    del body["data"][1]
    value = parse_fear_greed(body, NOW)
    assert value.daily_change is None
    assert "전일 비교 자료 없음" in fear_card(FeedState("fear", value, NOW), NOW)
    assert 'data-status="stale"' in fear_card(FeedState("fear", value, NOW), NOW + timedelta(days=3))
    assert 'data-status="stale"' in fear_card(FeedState("fear", value, NOW, "자료원 연결 지연"), NOW)
    assert "조회 지연" in fear_card(FeedState("fear", error="자료원 연결 지연"), NOW)
    assert "불러오는 중" in fear_card(FeedState("fear", loading=True), NOW)
    with pytest.raises(ValueError):
        parse_fear_greed(payload(), NOW + timedelta(days=8))


def test_daily_feed_uses_shared_single_flight_hour_cache_and_preserves_last_good_on_rate_limit():
    release, started = Event(), Event()
    clock, calls = [NOW], []
    value = parse_fear_greed(payload(), NOW)

    def fetch(key, now):
        calls.append(key)
        if len(calls) == 1:
            started.set()
            assert release.wait(2)
            return value
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "600"
        raise requests.HTTPError(response=response)

    service = MarketContextService(fetch, lambda: clock[0], keys=("fear",))
    try:
        service.snapshot()
        assert started.wait(1)
        for _ in range(20):
            assert service.snapshot().feed("fear").loading
        assert calls == ["fear"]
        release.set()
        idle(service)
        clock[0] += timedelta(minutes=59)
        assert idle(service).feed("fear").value is value and calls == ["fear"]
        clock[0] += timedelta(minutes=2)
        failed = idle(service).feed("fear")
        assert failed.value is value and failed.error and failed.updated_at == NOW
        clock[0] += timedelta(minutes=5)
        idle(service)
        assert len(calls) == 2
    finally:
        release.set()
        service.close()


def test_heatmap_uses_kst_weekdays_actual_four_hour_endpoint_returns_and_counts():
    frame = hours()
    report = hourly_heatmap(frame, cutoff(frame))
    monday = next(cell for cell in report.cells if cell.weekday == 0 and cell.hour == 0)
    assert (report.bars, report.blocks, len(report.cells)) == (672, 168, 42)
    assert monday.samples == 4 and monday.median_return == pytest.approx(0.04)
    assert all(cell.samples == 4 for cell in report.cells)
    assert next(cell for cell in report.cells if cell.weekday == 6 and cell.hour == 20).median_return == 0
    fortnight = hourly_heatmap(frame, cutoff(frame), 14)
    assert fortnight.blocks == 84 and all(cell.samples == 2 for cell in fortnight.cells)
    html = heatmap_card(report)
    assert html.count('type="radio"') == 42 and "4시간 등락 중앙값 +4.00%" in html
    assert "2개 이상의 관측이 필요해요" not in html and "빈 칸은 자료 부족" in html


def test_incomplete_invalid_duplicate_or_future_hours_never_create_a_complete_block():
    frame = hours()
    end = cutoff(frame)
    future = frame.iloc[:4].copy()
    future.index = pd.date_range(end, periods=4, freq="h")
    assert hourly_heatmap(pd.concat([frame, future]), end) == hourly_heatmap(frame, end)
    for broken in (
        frame.drop(frame.index[0]),
        pd.concat([frame, frame.iloc[[0]]]),
        frame.assign(high=frame.high.mask(frame.index == frame.index[0], np.nan)),
    ):
        report = hourly_heatmap(broken, end)
        assert report.blocks == 167
        assert report.cells[0].samples == 3
    short = frame.iloc[-24:]
    assert all(cell.median_return is None for cell in hourly_heatmap(short, end).cells)
    assert all(cell.median_return is None for cell in hourly_heatmap(None, end).cells)
    with pytest.raises(ValueError):
        hourly_heatmap(frame, end, 7)


def test_older_bar_revisions_invalidate_content_cache_without_refetching_history():
    frame = hours()
    cached_heatmap.clear()
    before = cached_heatmap(frame, cutoff(frame), 30)
    changed = frame.copy()
    changed.iloc[0, changed.columns.get_loc("high")] = 1
    assert changed.iloc[-1].equals(frame.iloc[-1])
    after = cached_heatmap(changed, cutoff(frame), 30)
    assert before != after and before.blocks == 168 and after.blocks == 167
    assert cached_heatmap(frame, cutoff(frame), 30) == before
