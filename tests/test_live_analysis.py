"""Live continuation agrees with full-history indicators without tick leakage."""

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.candles import candle_close, candle_boundary
from btc_analyzer.config import IndicatorConfig
from btc_analyzer.data.service import demo_bundle
from btc_analyzer.indicators.core import indicators
from btc_analyzer.ui.live_analysis import LIVE_ANALYSIS_JS, live_seed_json


def javascript(body, payload=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is a development-only browser engine check")
    pure = LIVE_ANALYSIS_JS.split("function makeLiveAnalysis")[0]
    program = "const input=JSON.parse(require('fs').readFileSync(0,'utf8'));" + pure + body
    result = subprocess.run(
        [node, "-e", program], input=json.dumps(payload), text=True, capture_output=True, check=True
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("tf", ["1h", "4h", "1d", "1w", "1M"])
@pytest.mark.parametrize("bars", [14, 25, 33, 79, 300])
def test_live_recursive_and_rolling_values_match_full_history(tf, bars):
    cfg = IndicatorConfig()
    raw = demo_bundle(tf, bars=bars + 1, end="2026-10-01T00:00Z")[tf]
    base, current = raw.iloc[:-1], raw.iloc[-1]
    enriched = indicators(base, cfg, tf)
    payload = json.loads(live_seed_json({tf: enriched}, cfg))
    k = {
        "at": int(raw.index[-1].timestamp() * 1000),
        "end": int(candle_close(raw.index[-1], tf).timestamp() * 1000),
        "row": [int(raw.index[-1].timestamp() * 1000), *map(float, current)],
    }
    actual = javascript(
        "console.log(JSON.stringify(LiveCandles.advance(input.seed,input.k,input.cfg).features))",
        {"seed": payload["frames"][tf], "k": k, "cfg": payload["cfg"]},
    )
    expected = indicators(raw, cfg, tf).iloc[-1]
    for name, value in actual.items():
        if name in ("ema_12", "ema_26"):
            continue
        if pd.isna(expected[name]):
            assert value is None, name
        else:
            assert value == pytest.approx(float(expected[name]), rel=2e-11, abs=1e-8), name


def test_gap_seed_restarts_and_missing_live_candles_are_not_smoothed():
    cfg = IndicatorConfig()
    raw = demo_bundle("1h", bars=300, end="2026-10-01T00:00Z")["1h"].drop(
        demo_bundle("1h", bars=300, end="2026-10-01T00:00Z")["1h"].index[-11]
    )
    payload = json.loads(live_seed_json({"1h": indicators(raw, cfg, "1h")}, cfg))
    seed = payload["frames"]["1h"]
    assert seed["count"] == len(seed["rows"]) == 10 and seed["gain"] is None
    assert (
        javascript(
            "console.log(JSON.stringify(LiveCandles.advance(input.seed,input.k,input.cfg)))",
            {"seed": seed, "k": {"at": seed["end"] + 3600000}, "cfg": payload["cfg"]},
        )
        is None
    )


def test_protocol_calendar_boundaries_and_bad_packets():
    now = int(pd.Timestamp("2026-10-08T00:23:00Z").timestamp() * 1000)
    packets = []
    for tf in ("1h", "4h", "1d", "1w", "1M"):
        start = candle_boundary(pd.Timestamp(now, unit="ms", tz="UTC"), tf)
        end = candle_close(start, tf)
        packets.append(
            {
                "e": "kline",
                "E": now,
                "s": "BTCUSDT",
                "k": {
                    "i": tf,
                    "s": "BTCUSDT",
                    "t": int(start.timestamp() * 1000),
                    "T": int(end.timestamp() * 1000) - 1,
                    "o": "100",
                    "h": "102",
                    "l": "99",
                    "c": "101",
                    "v": "0",
                    "x": False,
                },
            }
        )
    results = javascript(
        "console.log(JSON.stringify(input.packets.map(p=>LiveCandles.parse(p,input.now))))",
        {"packets": packets, "now": now},
    )
    assert all(result for result in results)
    assert results[-1]["end"] == int(pd.Timestamp("2026-11-01T00:00Z").timestamp() * 1000)
    assert results[-2]["at"] == int(pd.Timestamp("2026-10-05T00:00Z").timestamp() * 1000)
    rejected = []
    for field, value, nested in (
        ("s", "ETHUSDT", False),
        ("s", "ETHUSDT", True),
        ("E", now - 15001, False),
        ("E", now + 3001, False),
        ("t", now, True),
        ("T", now, True),
        ("i", "5m", True),
        ("x", "false", True),
        ("o", 0, True),
        ("h", "100", True),
        ("l", "102", True),
        ("c", "NaN", True),
        ("v", None, True),
        ("v", "", True),
        ("v", -1, True),
    ):
        packet = json.loads(json.dumps(packets[0]))
        (packet["k"] if nested else packet)[field] = value
        rejected.append(packet)
    assert javascript(
        "console.log(JSON.stringify(input.packets.map(p=>LiveCandles.parse(p,input.now))))",
        {"packets": rejected, "now": now},
    ) == [None] * len(rejected)


def test_forming_price_does_not_modify_cached_closed_seed_or_model():
    cfg = IndicatorConfig()
    raw = demo_bundle("1d", bars=301, end="2026-10-01T00:00Z")["1d"]
    encoded = live_seed_json({"1d": indicators(raw.iloc[:-1], cfg, "1d")}, cfg)
    payload = json.loads(encoded)
    seed = payload["frames"]["1d"]
    k = {
        "at": seed["end"],
        "end": seed["end"] + 86400000,
        "row": [seed["end"], 90000, 95000, 85000, 91000, 10],
    }
    result = javascript(
        """
      const original=JSON.stringify(input.seed);
      const first=LiveCandles.advance(input.seed,input.k,input.cfg);
      input.k.row[4]=94000;
      const second=LiveCandles.advance(input.seed,input.k,input.cfg);
      console.log(JSON.stringify({unchanged:original===JSON.stringify(input.seed),
        first:first.count,second:second.count,rsi:first.features.rsi,changed:second.features.rsi}));
    """,
        {"seed": seed, "k": k, "cfg": payload["cfg"]},
    )
    assert result["unchanged"] and result["first"] == result["second"] == seed["count"] + 1
    assert result["rsi"] != result["changed"] and json.loads(encoded)["frames"]["1d"] == seed


def test_closed_candle_commits_once_and_next_candle_continues_full_history():
    cfg = IndicatorConfig()
    raw = demo_bundle("1h", bars=303, end="2026-10-01T00:00Z")["1h"]
    payload = json.loads(live_seed_json({"1h": indicators(raw.iloc[:-2], cfg, "1h")}, cfg))
    candles = [
        {
            "at": int(t.timestamp() * 1000),
            "end": int(candle_close(t, "1h").timestamp() * 1000),
            "row": [int(t.timestamp() * 1000), *map(float, row)],
        }
        for t, row in raw.tail(2).iterrows()
    ]
    result = javascript(
        """
      const closed=LiveCandles.advance(input.seed,input.candles[0],input.cfg);
      const duplicate=LiveCandles.advance(closed,input.candles[0],input.cfg);
      const next=LiveCandles.advance(closed,input.candles[1],input.cfg);
      console.log(JSON.stringify({duplicate,features:next.features,count:next.count,rows:next.rows.length}));
    """,
        {"seed": payload["frames"]["1h"], "cfg": payload["cfg"], "candles": candles},
    )
    assert result["duplicate"] is None and result["count"] == len(raw) and result["rows"] == 80
    expected = indicators(raw, cfg, "1h").iloc[-1]
    assert result["features"]["rsi"] == pytest.approx(float(expected.rsi))
    assert result["features"]["macd_hist"] == pytest.approx(float(expected.macd_hist))


def test_forecast_live_layer_preserves_model_and_shares():
    from btc_analyzer.analysis.forecast import predict_history
    from btc_analyzer.analysis.direction_outlook import direction_outlook
    from btc_analyzer.ui.forecast_view import prediction_chart

    frame = demo_bundle("1d", bars=1000, end="2026-10-01T00:00Z")["1d"]
    result = predict_history(frame, "1d", candle_close(frame.index[-1], "1d"), 30, 30)
    outlook = direction_outlook(result)
    fig = prediction_chart(result, "Asia/Seoul", "USDT", outlook=outlook)
    meta = fig.layout.meta["btcLive"]
    assert meta["liveIndices"] == [6, 7, 8]
    assert meta["offsets"][0] == 0 and meta["offsets"][-1] == 30 * 86400000
    for scenario, trace in zip(outlook.scenarios, fig.data[3:6]):
        assert trace.y == tuple(np.round(scenario.center, 2))
        assert trace.meta["share"] == scenario.share
    assert all(all(y is None for y in trace.y) for trace in fig.data[6:])
    assert meta["center"][0] == meta["anchor"]
    assert "run_every=60" in (Path(__file__).resolve().parents[1] / "app.py").read_text()
