"""Viewport math, readable dates, on-demand short candles and calendar horizons."""

import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from btc_analyzer.analysis.forecast import horizon_days
from btc_analyzer.data.nasdaq import horizon_bars, trading_dates


def test_pinch_preserves_anchor_and_auto_uses_only_visible_candles():
    source = Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/browser/chart-viewport.js"
    script = (
        source.read_text()
        + """
console.log(JSON.stringify({
  zoom:ChartViewport.pinch([0,100],50,50,100,2),
  more:ChartViewport.pinch([0,100],50,50,100,.5),
  pan:ChartViewport.pinch([0,100],50,60,100,1),
  limited:ChartViewport.limit([-20,30],{min:0,max:100,step:1,count:100}),
  fit:ChartViewport.extent([0,1,2,3],[1,100,101,1],[9999,102,103,9999],[1,2]),
  date:ChartViewport.label(Date.UTC(2026,9,17,12,34))
}));"""
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data["zoom"] == [25, 75] and data["more"] == [-50, 150] and data["pan"] == [-10, 90]
    assert data["limited"] == [0, 50]
    assert data["fit"]["range"] == pytest.approx([99.64, 103.36])
    assert "12:34" in data["date"] and "179" not in data["date"]


@pytest.mark.parametrize(
    "start,horizon,days", [("2024-01-31", "2mo", 60), ("2025-01-31", "2mo", 59), ("2026-12-30", "2w", 14)]
)
def test_two_month_and_two_week_dates_use_calendar(start, horizon, days):
    assert horizon_days(pd.Timestamp(start, tz="UTC"), horizon) == days


def test_nq_added_horizons_count_actual_trading_closes():
    origin = pd.Timestamp("2026-10-16T21:00Z")
    assert horizon_bars(origin, "2w") == 10
    count = horizon_bars(origin, "2mo")
    dates = trading_dates(origin, "1d", count + 2)
    assert dates[count] <= origin + pd.DateOffset(months=2) < dates[count + 1]


@pytest.mark.usefixtures("offline_dashboard")
def test_short_charts_and_six_periods_share_existing_analysis(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(root / "web_app.py", default_timeout=60).run()
    assert not app.exception and not app.error
    for tf in ("5m", "15m"):
        next(x for x in app.get("button_group") if x.label == "차트 시간대").set_value(tf).run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        assert spec["layout"]["meta"]["btcLive"]["timeframe"] == tf
        assert len(spec["data"][0]["x"]) == 600
        assert any("btc-chart-seed" in m.value for m in app.markdown)
    app.session_state["dashboard_tab"] = "미래 예측"
    app.run()
    for horizon in ("2w", "2mo"):
        next(x for x in app.get("button_group") if x.label == "예측 기간").set_value(horizon)
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run()
        assert not app.exception and not app.error
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        origin = pd.Timestamp(spec["data"][3]["x"][0])
        target = origin + (pd.Timedelta(weeks=2) if horizon == "2w" else pd.DateOffset(months=2))
        assert pd.Timestamp(spec["data"][3]["x"][-1]) == target
    assert any("OpenAI 연결 대기" in item.value for item in app.info)
