"""Conditional lines agree with full-history equations, without future leakage."""

import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.projected_indicators import projection_seed, project_indicators
from btc_analyzer.data.service import demo_bundle


def test_projected_path_matches_recomputing_indicators_and_does_not_double_count_anchor():
    raw = demo_bundle("1d", bars=260, end="2026-10-01T00:00Z")["1d"]
    cutoff = pd.Timestamp("2026-10-01T00:00Z")
    seed = projection_seed(raw, "1d", cutoff)
    path = [
        float(raw.close.iloc[-1]),
        *np.linspace(float(raw.close.iloc[-1]) * 0.9, float(raw.close.iloc[-1]) * 1.2, 30),
    ]
    actual = project_indicators(seed, path)
    history = raw.close.tolist() + path[1:]
    series = pd.Series(history)
    for n in (20, 50, 200):
        expected = series.ewm(span=n, adjust=False, min_periods=n).mean().iloc[-len(path) :]
        assert actual[f"ema_{n}"] == pytest.approx(expected)
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


def test_short_history_stays_missing_until_sufficient_forecast_observations():
    seed = {"count": 18, "ema": {"20": 100.0, "50": 100.0, "200": 100.0}, "tail": [100.0] * 18}
    result = project_indicators(seed, [100.0, 101.0, 102.0, 103.0])
    assert result["ema_20"][:2] == [None, None]
    assert result["ema_50"] == [None] * 4 and result["bb_middle"][:2] == [None, None]
    assert result["ema_20"][2] is not None and seed["count"] == 18
