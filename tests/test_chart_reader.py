"""Displayed values retain missing history and selected asset precision."""

import pandas as pd
import pytest

from btc_analyzer.ui.chart_reader import reader_html


def test_reader_keeps_xrp_prices_and_missing_averages_distinct():
    frame = pd.DataFrame(
        {
            "open": [1.1532],
            "high": [1.1634],
            "low": [1.1401],
            "close": [1.1535],
            "ema_20": [float("nan")],
            "bb_upper": [None],
            "bb_middle": [1.1500],
            "bb_lower": [1.1100],
        },
        index=pd.DatetimeIndex(["2026-10-16T00:00Z"]),
    )
    html = reader_html(frame, "1d", "XRP", ("ema_20", "ema_200"), True)
    assert 'data-symbol="XRPUSDT"' in html and 'data-decimals="4"' in html
    assert 'data-field="close">1.1535' in html and 'data-field="ema_20">—' in html
    assert 'data-field="ema_200">—' in html and 'data-field="bb_upper">—' in html
    assert "data-current-label>현재 가격</span>" in html and 'data-field="current">—</b>' in html
    assert "현재가 연결 중" in html
    assert 'data-field="cursor"' not in html
    assert "nan" not in html and "10.16 09:00 KST" in html
    bare = reader_html(frame, "1d", "XRP", (), False)
    assert "EMA" not in bare and "볼린저" not in bare


@pytest.mark.parametrize("tf", ["1h", "4h", "1d", "1w", "1M"])
def test_compact_plot_dates_keep_display_time_and_utc_close_boundary(tf):
    from btc_analyzer.candles import candle_close
    from btc_analyzer.data.service import demo_bundle
    from btc_analyzer.indicators.core import indicators
    from btc_analyzer.ui.market_view import market_chart_spec

    raw = demo_bundle(tf, bars=230, end="2026-10-01T00:00Z")[tf]
    frame = indicators(raw, timeframe=tf)
    spec = market_chart_spec(frame, "Asia/Seoul", ("ema_20",), True, "USDT", False, False, 120, tf, 26)
    end = frame.index[-1]
    wall_time = int(end.tz_convert("Asia/Seoul").tz_localize(None).value // 1_000_000)
    timeline = spec["layout"]["meta"]["btcLive"]["timeline"]
    assert timeline["source"][-1] == wall_time
    final_position = timeline["origin"] + (len(timeline["source"]) - 1) * timeline["step"]
    assert all(trace["x"][-1] == final_position for trace in spec["data"])
    assert spec["layout"]["xaxis"]["type"] == "date"
    assert not spec["layout"].get("transition")  # Even duration=0 starts a native axis RAF.
    assert spec["layout"]["meta"]["btcLive"]["closedEnd"] == int(candle_close(end, tf).timestamp() * 1000)
