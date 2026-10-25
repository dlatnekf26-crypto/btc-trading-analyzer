from datetime import datetime, timezone
import numpy as np
from btc_analyzer.data.market_caps import parse_cap, cap_order, Capitalization
from btc_analyzer.ui.oscillator_chart import macd_colors


def test_macd_only_highlights_actual_crossings_and_does_not_bridge_missing_values():
    assert macd_colors([-2, -1, 1, 2, 0, -1, np.nan, 1]) == [
        "#e94b65",
        "#e94b65",
        "#8b5cf6",
        "#10a878",
        "#10a878",
        "#f59e0b",
        "#e94b65",
        "#10a878",
    ]


def test_caps_validate_currency_dates_identity_and_sort_unknown_last():
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    row = {"asOfDate": "2026-10-01", "currencyCode": "USD", "reportedValue": {"raw": 1234}}

    def payload(item):
        return {"timeseries": {"result": [{"meta": {"symbol": ["MSFT"]}, "trailingMarketCap": [item]}]}}

    assert parse_cap(payload(row), "MSFT", now).value == 1234
    for patch in (
        {"currencyCode": "KRW"},
        {"asOfDate": "2026-10-26"},
        {"reportedValue": {"raw": float("nan")}},
    ):
        assert parse_cap(payload({**row, **patch}), "MSFT", now) is None
    assert parse_cap(payload(row), "AAPL", now) is None
    caps = {
        "AAPL": Capitalization(200, "USD", "2026-10-01"),
        "MSFT": Capitalization(300, "USD", "2026-10-01"),
    }
    assert cap_order(["NVDA", "AAPL", "MSFT"], caps) == ["MSFT", "AAPL", "NVDA"]
