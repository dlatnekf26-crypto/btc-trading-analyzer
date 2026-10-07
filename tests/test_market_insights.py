"""Daily sentiment freshness, cache/backoff and complete, causal KST heatmaps."""

from datetime import datetime, timedelta, timezone
from threading import Event
import time

import numpy as np
import pandas as pd
import pytest
import requests

from btc_analyzer.analysis.monthly_heatmap import monthly_heatmap
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


def months():
    index = pd.date_range("2022-01-01", "2026-09-01", freq="MS", tz="UTC")
    change = np.where(index.month == 1, (index.year - 2021) * 0.1, 0)
    closing = 100 * (1 + change)
    return pd.DataFrame(
        dict(open=100.0, high=np.maximum(100, closing) * 1.01, low=99.0, close=closing), index=index
    )


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
    assert "자동 확인 · 일별 지수" in html and "실시간" not in html
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


def test_daily_feed_uses_shared_single_flight_minute_cache_and_preserves_last_good_on_rate_limit():
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
        clock[0] += timedelta(seconds=59)
        assert idle(service).feed("fear").value is value and calls == ["fear"]
        clock[0] += timedelta(seconds=2)
        failed = idle(service).feed("fear")
        assert failed.value is value and failed.error and failed.updated_at == NOW
        clock[0] += timedelta(minutes=5)
        idle(service)
        assert len(calls) == 2
    finally:
        release.set()
        service.close()


def test_multi_year_monthly_returns_and_average_only_include_real_closed_months():
    report = monthly_heatmap(months(), NOW)
    assert report.years == (2026, 2025, 2024, 2023, 2022)
    assert (report.bars, len(report.cells), len(report.averages)) == (57, 60, 12)
    january = next(c for c in report.cells if c.year == 2022 and c.month == 1)
    assert january.change == pytest.approx(0.1)
    assert report.averages[0].samples == 5 and report.averages[0].change == pytest.approx(0.3)
    assert report.averages[9].samples == 4 and report.averages[9].change == 0
    assert next(c for c in report.cells if c.year == 2026 and c.month == 10).status == "open"
    html = heatmap_card(report)
    assert html.count('type="radio"') == 72
    assert "2022–2026" in html and "1月" not in html and "月" not in html
    assert "1월 역사적 평균 · 5개 연도" in html and "관측 월 등락률 평균 +30.00%" in html
    assert "진행 중/빈 칸은 평균 제외" in html


def test_minute_refresh_receives_provider_updates_with_original_daily_source_time():
    clock, calls = [NOW], []

    def fetch(key, now):
        calls.append(now)
        body = payload()
        body["data"][0]["value"] = str(20 + len(calls) - 1)
        return parse_fear_greed(body, now)

    service = MarketContextService(fetch, lambda: clock[0], keys=("fear",))
    try:
        first = idle(service).feed("fear")
        clock[0] += timedelta(seconds=59)
        assert idle(service).feed("fear").value.latest.value == 20 and len(calls) == 1
        clock[0] += timedelta(seconds=2)
        latest = idle(service).feed("fear")
        assert len(calls) == 2 and latest.value.latest.value == 21
        assert latest.value.latest.timestamp == first.value.latest.timestamp
        assert latest.updated_at == clock[0]
        html = fear_card(latest, clock[0])
        assert 'data-score="21"' in html and "1분마다 최신 값 확인" in html and "원자료는 일별 발표" in html
    finally:
        service.close()


def test_month_close_uses_utc_calendar_boundaries_including_leap_february():
    frame = months().tz_convert("Asia/Seoul")
    before = monthly_heatmap(frame, pd.Timestamp("2024-02-29T23:59:59Z"))
    after = monthly_heatmap(frame, pd.Timestamp("2024-03-01T00:00:00Z"))
    assert before.bars + 1 == after.bars
    assert next(c for c in before.cells if c.year == 2024 and c.month == 2).change is None
    assert next(c for c in after.cells if c.year == 2024 and c.month == 2).change == 0
    assert before.averages[1].samples + 1 == after.averages[1].samples


def test_missing_invalid_duplicate_and_future_months_never_fill_historical_averages():
    frame = months()
    baseline = monthly_heatmap(frame, NOW)
    future = frame.iloc[:3].copy()
    future.index = pd.date_range("2026-10-01", periods=3, freq="MS", tz="UTC")
    future.close *= 10
    assert monthly_heatmap(pd.concat([frame, future]), NOW) == baseline
    for broken in (
        frame.drop(frame.index[0]),
        pd.concat([frame, frame.iloc[[0]]]),
        frame.assign(high=frame.high.mask(frame.index == frame.index[0], np.nan)),
    ):
        report = monthly_heatmap(broken, NOW)
        assert report.bars == 56 and report.averages[0].samples == 4
        assert report.averages[0].change == pytest.approx(0.35)
        assert next(c for c in report.cells if c.year == 2022 and c.month == 1).change is None
    offgrid = frame.copy()
    offgrid.index += pd.Timedelta(hours=1)
    assert monthly_heatmap(offgrid, NOW).bars == 0
    assert monthly_heatmap(frame.tz_localize(None), NOW).bars == 0
    assert monthly_heatmap(None, NOW).bars == 0
    with pytest.raises(ValueError):
        monthly_heatmap(frame, NOW.replace(tzinfo=None))


def test_period_mean_and_content_cache_follow_full_history_revisions():
    frame = months()
    old = frame.iloc[:12].copy()
    old.index -= pd.DateOffset(years=4)
    full = pd.concat([old, frame])
    all_years = monthly_heatmap(full, NOW)
    five = monthly_heatmap(full, NOW, 5)
    assert all_years.years[-1] == 2018 and five.years[-1] == 2022
    assert all_years.averages[0].samples == 6 and five.averages[0].samples == 5
    cached_heatmap.clear()
    before = cached_heatmap(frame, NOW, 0)
    changed = frame.copy()
    changed.iloc[0, changed.columns.get_loc("high")] = 1
    assert changed.iloc[-1].equals(frame.iloc[-1])
    after = cached_heatmap(changed, NOW, 0)
    assert before != after and after.averages[0].samples == 4
    assert cached_heatmap(frame, NOW, 0) == before
    with pytest.raises(ValueError):
        monthly_heatmap(frame, NOW, 30)


def test_binance_launch_partial_month_is_visible_but_excluded_from_seasonal_average():
    frame = months().iloc[:2].copy()
    frame.index = pd.DatetimeIndex(["2017-08-01", "2018-08-01"], tz="UTC")
    report = monthly_heatmap(frame, NOW)
    launch = next(c for c in report.cells if c.year == 2017 and c.month == 8)
    assert launch.change == pytest.approx(0.1) and launch.status == "partial"
    assert report.averages[7].samples == 1 and report.averages[7].change == 0
    assert "거래 시작 부분월 · 평균 제외" in heatmap_card(report)
