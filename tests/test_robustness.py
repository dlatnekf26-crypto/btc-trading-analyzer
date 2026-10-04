"""Risk metrics, holdout boundaries, seed reproducibility and conservative evidence gates."""

import numpy as np
import pandas as pd
import pytest
from btc_analyzer.backtest.metrics import metrics
from btc_analyzer.backtest.monte_carlo import monte_carlo
from btc_analyzer.backtest.robustness import run_robustness
from btc_analyzer.backtest.walk_forward import split_evaluation, walk_forward
from btc_analyzer.config import AppConfig


def test_monte_carlo_reproducible_and_drawdown_from_initial():
    trades = pd.DataFrame({"r_multiple": [-1, -1, -1]})
    a = monte_carlo(trades, initial=10000, risk=0.01, seed=17)
    b = monte_carlo(trades, initial=10000, risk=0.01, seed=17)
    assert a["simulations"] == 1000
    assert a["worst_drawdown"] == pytest.approx(1 - 0.99**3)
    assert a["worst_losing_streak"] == 3
    np.testing.assert_array_equal(a["drawdowns"], b["drawdowns"])
    pd.testing.assert_frame_equal(a["equity_bands"], b["equity_bands"])
    assert not monte_carlo(pd.DataFrame())["available"]
    with pytest.raises(ValueError):
        monte_carlo(trades, simulations=100)


def test_metric_known_values():
    equity = pd.Series([10000, 11000, 8800, 10500], index=pd.date_range("2025-01-01", periods=4, tz="UTC"))
    trades = pd.DataFrame(
        {
            "pnl": [1000, -2200, 1700],
            "r_multiple": [1, -2.2, 1.7],
            "holding_hours": [2, 4, 6],
            "fees": [2, 3, 4],
        }
    )
    m = metrics(equity, trades, 10000)
    assert m["total_return"] == pytest.approx(0.05)
    assert m["maximum_drawdown"] == pytest.approx(0.2)
    assert m["profit_factor"] == pytest.approx(2700 / 2200)
    assert m["expectancy"] == pytest.approx(500 / 3)
    assert m["average_holding_hours"] == 4
    assert m["fees_paid"] == 9
    assert m["cagr"] is None
    assert m["win_rate"] == pytest.approx(2 / 3)


def test_chronological_holdout_boundaries(bundle):
    r = split_evaluation(bundle, "1h", AppConfig())
    spans = [x.equity.index for x in r.values()]
    assert spans[0][-1] <= spans[1][0]
    assert spans[1][-1] <= spans[2][0]
    assert all(x.metrics["initial_capital"] == 10000 for x in r.values())


def test_walk_forward_training_precedes_test(bundle):
    cfg = AppConfig()
    report = walk_forward(
        bundle, "1h", cfg, train_bars=200, validation_bars=60, test_bars=60, candidates=[cfg]
    )
    assert len(report) >= 2
    for r in report.itertuples():
        assert pd.Timestamp(r.train_start) < pd.Timestamp(r.train_end) <= pd.Timestamp(r.validation_start)
        assert pd.Timestamp(r.validation_start) < pd.Timestamp(r.test_start) < pd.Timestamp(r.test_end)
    assert report.test_end.iloc[0] <= report.test_start.iloc[1]


def test_full_robustness_preserves_no_trade_evidence(bundle):
    r = run_robustness(bundle, "1h", AppConfig(), compact=True)
    assert set(r["splits"]) == {"In-Sample", "Validation", "Out-of-Sample"}
    assert len(r["parameters"]) == 3
    assert list(r["costs"].cost_multiplier) == [1, 1.5, 2]
    assert not r["assessment"]["live_orders_enabled"]
    assert r["assessment"]["final_classification"] != "Production Candidate"
    if r["splits"]["Out-of-Sample"].metrics["number_of_trades"] < 30:
        assert r["assessment"]["out_of_sample"] == "Warning"
