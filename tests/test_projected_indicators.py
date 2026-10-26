"""Conditional lines agree with full-history equations, without future leakage."""

import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.projected_indicators import projection_seed, project_indicators
from btc_analyzer.data.service import demo_bundle


@pytest.mark.parametrize("market", ["BTC", "SAMSUNG"])
def test_projected_path_matches_recomputing_indicators_and_does_not_double_count_anchor(market):
    raw = demo_bundle("1d", bars=260, end="2026-10-01T00:00Z")["1d"]
    if market == "SAMSUNG":
        from btc_analyzer.data.exchange_history import calendar_bars

        from btc_analyzer.market_clock import SessionTimes

        starts, ends = calendar_bars("2024-01-01", "2026-10-02", "1d", market)
        raw.index = starts[ends <= pd.Timestamp("2026-10-01T00:00Z")][-len(raw) :]
        raw.attrs.update(
            market=market, bar_starts=SessionTimes(starts.asi8), bar_ends=SessionTimes(ends.asi8)
        )
    cutoff = pd.Timestamp("2026-10-01T00:00Z")
    seed = projection_seed(raw, "1d", cutoff)
    path = [
        float(raw.close.iloc[-1]),
        *np.linspace(float(raw.close.iloc[-1]) * 0.9, float(raw.close.iloc[-1]) * 1.2, 30),
    ]
    actual = project_indicators(seed, path)
    history = raw.close.tolist() + path[1:]
    series = pd.Series(history)
    periods = (20, 60, 120) if market == "SAMSUNG" else (20, 50, 200)
    for n in periods:
        average = (
            series.rolling(n).mean()
            if market == "SAMSUNG"
            else series.ewm(span=n, adjust=False, min_periods=n).mean()
        )
        expected = average.iloc[-len(path) :]
        assert actual[f"{'sma' if market == 'SAMSUNG' else 'ema'}_{n}"] == pytest.approx(expected)
    assert set(actual) == {
        *(f"{'sma' if market == 'SAMSUNG' else 'ema'}_{n}" for n in periods),
        "bb_upper",
        "bb_middle",
        "bb_lower",
    }
    middle = series.rolling(20).mean().iloc[-len(path) :]
    deviation = series.rolling(20).std(ddof=0).iloc[-len(path) :] * 2
    assert actual["bb_upper"] == pytest.approx(middle + deviation)
    changed = raw.copy()
    changed.loc[cutoff] = [1, 2, 1, 1, 1]
    assert projection_seed(changed, "1d", cutoff) == seed

    js = Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/browser/project-indicators.js"
    script = (
        js.read_text()
        + "\nconst data=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(projectIndicators(data.seed,data.path)));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"seed": seed, "path": path}),
        text=True,
        capture_output=True,
        check=True,
    )
    browser = json.loads(result.stdout)
    for key in actual:
        assert browser[key] == pytest.approx(actual[key], rel=1e-11)
    gapped = projection_seed(raw.drop(raw.index[-5]), "1d", cutoff)
    assert gapped["count"] == 4
    assert all(
        project_indicators(gapped, path)[f"{'sma' if market == 'SAMSUNG' else 'ema'}_{n}"][0] is None
        for n in periods
    )


def test_short_history_stays_missing_until_sufficient_forecast_observations():
    seed = {"count": 18, "ema": {"20": 100.0, "50": 100.0, "200": 100.0}, "tail": [100.0] * 18}
    result = project_indicators(seed, [100.0, 101.0, 102.0, 103.0])
    assert result["ema_20"][:2] == [None, None]
    assert result["ema_50"] == [None] * 4 and result["bb_middle"][:2] == [None, None]
    assert result["ema_20"][2] is not None and seed["count"] == 18


def test_domestic_projection_waits_for_each_complete_average_window():
    seed = {"count": 58, "ema": {}, "sma": [20, 60, 120], "tail": list(range(1, 59))}
    result = project_indicators(seed, [58, 59, 60, 61])
    assert result["sma_60"][:2] == [None, None]
    assert result["sma_60"][2:] == pytest.approx([30.5, 31.5])
    assert result["sma_120"] == [None] * 4
    assert seed["tail"] == list(range(1, 59))
