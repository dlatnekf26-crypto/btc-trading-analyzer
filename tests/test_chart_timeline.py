"""Every chart period compresses market closures without altering actual data."""

import json
import subprocess
from copy import deepcopy

import numpy as np
import pytest

from btc_analyzer.config import CHART_TIMEFRAMES
from btc_analyzer.ui.browser_assets import browser_asset
from btc_analyzer.ui.chart_timeline import compact_timeline


@pytest.mark.parametrize("timeframe", CHART_TIMEFRAMES)
def test_closed_market_gaps_are_compacted_in_every_period(timeframe):
    times = [1700000000000, 1700000300000, 1700259200000]
    spec = {
        "data": [
            {"type": "candlestick", "x": times[:], "close": [100, 110, 105]},
            {"type": "scatter", "x": [times[0], None, times[-1]], "y": [1, None, 2]},
        ],
        "layout": {"xaxis": {}, "xaxis2": {}, "meta": {"btcLive": {}}},
    }
    original = deepcopy(spec)
    result = compact_timeline(spec, times, timeframe, 3)
    assert np.ptp(np.diff(result["data"][0]["x"])) == 0
    assert result["data"][0]["close"] == original["data"][0]["close"]
    assert result["data"][1]["x"][1] is None
    assert result["layout"]["meta"]["btcLive"]["timeline"]["source"] == times
    assert result["layout"]["xaxis"]["ticktext"] == result["layout"]["xaxis2"]["ticktext"]


def test_source_dates_and_display_coordinates_round_trip_for_live_updates():
    source = (
        browser_asset("plot-data.js")
        + browser_asset("chart-viewport.js")
        + """
const plot={layout:{meta:{btcLive:{timeline:{source:[10,20,1000,1100],origin:0,step:100}}}}};
for(const time of [10,15,20,510,1000,1100,1200]){
 const position=PlotData.chartTime(plot,time);
 if(Math.abs(PlotData.sourceTime(plot,position)-time)>1e-8)throw Error('lost date '+time);
}
console.log(JSON.stringify({gap:PlotData.chartTime(plot,1000)-PlotData.chartTime(plot,20),
 ticks:PlotData.ticks(plot,[0,300]).tickvals.length}));
"""
    )
    result = subprocess.run(["node", "-e", source], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"gap": 100, "ticks": 4}


def test_pending_preview_does_not_crash_after_plotly_layout_is_removed():
    program = (
        "const ChartCanvas={preview(){},clear(){}};"
        + browser_asset("chart-preview.js")
        + """
const preview=ChartPreview.create({layout:{},querySelector(){return null;}});
preview.show([0,1],{});preview.clear();
console.log(JSON.stringify({supported:preview.supported}));
"""
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"supported": False}
