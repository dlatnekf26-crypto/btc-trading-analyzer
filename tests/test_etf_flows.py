"""Reported totals, missing publication and bounded public ETF parsing."""

from datetime import datetime, timezone
from threading import Event
import time

import pytest
from btc_analyzer.data.etf_flows import parse_etf_flows
from btc_analyzer.data.market_context import FeedState, MarketContextService
from btc_analyzer.ui.etf_view import etf_card

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def table(rows):
    return (
        "<table><tr><th>Date</th><th>IBIT</th><th>FBTC</th><th>Total</th></tr>"
        + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        + "</table>"
    ).encode()


def test_inflow_outflow_latest_partial_and_zero_are_distinct():
    value = parse_etf_flows(
        table(
            [
                ["13 Oct 2026", "100.0", "(40.0)", "60.0"],
                ["14 Oct 2026", "0.0", "0.0", "0.0"],
                ["15 Oct 2026", "—", "-", ""],
                ["Average", "200.0", "100.0", "300.0"],
            ]
        ),
        "BTC",
        NOW,
    )
    assert value.days[0].funds == (("IBIT", 100.0), ("FBTC", -40.0))
    assert value.latest.at.day == 14 and value.latest.net == 0
    assert value.days[-1].net is None and value.days[-1].funds[0][1] is None
    html = etf_card("BTC", FeedState("etf_BTC", value, NOW), NOW)
    assert "+0.0" in html and "10.15 집계 중" in html and "Farside" in html
    assert "최근 5거래일" not in html
    assert "갱신 지연" in etf_card("BTC", FeedState("etf_BTC", value, NOW, "error"), NOW)


@pytest.mark.parametrize(
    "row",
    [
        ["16 Oct 2026", "1", "2", "3"],
        ["14 Oct 2026", "1", "2", "3000"],
        ["14 Oct 2026", "NaN", "2", "3"],
        ["14 Oct 2026", "1", "2"],
        ["14 Oct 2026", "1e8", "2", "3"],
        ["14 Oct 2026", "1000001", "2", "3"],
    ],
)
def test_provider_errors_never_become_plausible_totals(row):
    with pytest.raises(ValueError):
        parse_etf_flows(table([row]), "BTC", NOW)


def test_conflicting_duplicates_and_non_tables_are_rejected():
    with pytest.raises(ValueError):
        parse_etf_flows(table([["14 Oct 2026", "1", "2", "3"], ["14 Oct 2026", "2", "2", "4"]]), "BTC", NOW)
    with pytest.raises(ValueError):
        parse_etf_flows(b"<html>Cloudflare unavailable</html>", "ETH", NOW)
    with pytest.raises(ValueError):
        parse_etf_flows(table([["14 Oct 2026", "1", "2", "3"]]), "ETH", NOW)


def test_shared_async_feed_preserves_last_report_on_failure_and_does_not_duplicate_requests():
    entered, release = Event(), Event()
    calls = []
    clock = [NOW]

    def fetch(key, now):
        calls.append(key)
        entered.set()
        release.wait(2)
        if len(calls) > 1:
            raise ValueError("source failed")
        return parse_etf_flows(table([["14 Oct 2026", "1", "2", "3"]]), "BTC", now)

    service = MarketContextService(
        fetcher=fetch, clock=lambda: clock[0], keys=["etf_BTC"], refresh_intervals={"etf_BTC": 600}, workers=1
    )
    try:
        service.snapshot()
        assert entered.wait(1)
        for _ in range(20):
            service.snapshot()
        assert calls == ["etf_BTC"]
        release.set()
        for _ in range(100):
            feed = service.snapshot().feed("etf_BTC")
            if not feed.loading:
                break
            time.sleep(0.005)
        assert feed.value.latest.net == 3
        from datetime import timedelta

        clock[0] += timedelta(minutes=11)
        service.snapshot()
        for _ in range(100):
            feed = service.snapshot().feed("etf_BTC")
            if not feed.loading:
                break
            time.sleep(0.005)
        assert len(calls) == 2 and feed.error and feed.value.latest.net == 3
    finally:
        release.set()
        service.close()


def test_ethereum_source_blank_date_heading_and_correct_asset_funds():
    body = (
        table([["14 Oct 2026", "100.0", "(50.0)", "50.0"]])
        .replace(b">Date<", b"><")
        .replace(b"IBIT", b"ETHA")
        .replace(b"FBTC", b"FETH")
    )
    value = parse_etf_flows(body, "ETH", NOW)
    assert value.latest.net == 50 and value.latest.funds[0][0] == "ETHA"
    with pytest.raises(ValueError):
        parse_etf_flows(body, "BTC", NOW)
