"""Exact cash-flow assertions, asymmetric slippage, ambiguous bars and next-open entry."""

from dataclasses import replace
import pandas as pd
import pytest
from btc_analyzer.config import AppConfig, RiskConfig, StrategyConfig
from btc_analyzer.risk.position_sizing import position_size
from btc_analyzer.risk.risk_manager import RiskGuard
from btc_analyzer.strategy.entry_engine import TradePlan, entry_plan
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.backtest.execution import open_position, advance_position, completed_trade
from btc_analyzer.backtest.engine import BacktestEngine


@pytest.fixture
def cfg():
    return AppConfig(strategy=StrategyConfig(min_rr=1.5), risk=RiskConfig(fee=0.001, slippage=0.0005))


@pytest.fixture
def plan():
    return TradePlan("long", 95, 105, 100, 90, (120, 130, 140), (2, 3, 4))


def test_position_sizing_includes_costs(cfg):
    size = position_size(10000, 100, 90, cfg.risk)
    stop_fill = 90 * (1 - 0.0005)
    expected = 100 / (100 - stop_fill + 0.001 * (100 + stop_fill))
    assert size.quantity == pytest.approx(expected)
    assert size.estimated_loss == pytest.approx(100)
    small_stop = position_size(100, 100, 99.99, cfg.risk)
    assert small_stop.notional * (1 + cfg.risk.fee) <= 100 + 1e-10


def test_entry_stop_targets_symmetric(features, cfg):
    for direction in ["long", "short"]:
        p = entry_plan(features.iloc[-1], [], direction, cfg.strategy)
        assert p.entry_low < p.entry_high
        sign = 1 if direction == "long" else -1
        assert sign * (p.entry - p.stop) > 0
        assert all(sign * (target - p.entry) > 0 for target in p.targets)
        assert p.rr[0] < p.rr[1] < p.rr[2]


def opened(plan, cfg):
    return open_position(
        plan,
        "2025-01-01T01:00Z",
        "2025-01-01T01:00Z",
        100,
        10000,
        cfg,
        1,
        regime="Uptrend",
        volatility="Normal Volatility",
        score=80,
        quality=90,
    )


def test_fee_slippage_exact(plan, cfg):
    p = opened(plan, cfg)
    assert p.entry == pytest.approx(100.05)
    q = p.quantity
    row = pd.Series({"open": 100, "high": 145, "low": 99, "close": 140})
    assert advance_position(p, row, "2025-01-01T02:00Z", cfg)
    trade = completed_trade(p)
    fills = [120 * 0.9995, 130 * 0.9995, 140 * 0.9995]
    expected = sum((price - p.entry) * q / 3 - price * q / 3 * 0.001 for price in fills) - p.entry * q * 0.001
    assert trade["pnl"] == pytest.approx(expected)
    assert trade["fees"] == pytest.approx(p.entry * q * 0.001 + sum(fills) * q / 3 * 0.001)
    assert len(trade["exits"]) == 3


def test_stop_wins_ambiguous_bar(plan, cfg):
    p = opened(plan, cfg)
    advance_position(
        p, pd.Series({"open": 100, "high": 150, "low": 85, "close": 120}), "2025-01-01T02:00Z", cfg
    )
    assert p.exits[0]["reason"] == "stop"
    assert p.exits[0]["price"] == pytest.approx(90 * 0.9995)
    assert p.pnl < 0


def test_stop_gap_worse_open(plan, cfg):
    p = opened(plan, cfg)
    advance_position(p, pd.Series({"open": 80, "high": 90, "low": 70, "close": 85}), "2025-01-01T02:00Z", cfg)
    assert p.exits[0]["price"] == pytest.approx(80 * 0.9995)


def test_outside_entry_expires(plan, cfg):
    assert (
        open_position(
            plan,
            "2025-01-01T01:00Z",
            "2025-01-01T01:00Z",
            110,
            10000,
            cfg,
            1,
            regime="Uptrend",
            volatility="Normal Volatility",
            score=80,
            quality=90,
        )
        is None
    )


def test_short_cost_symmetry(plan, cfg):
    short = TradePlan("short", 95, 105, 100, 110, (80, 70, 60), (2, 3, 4))
    p = opened(short, cfg)
    assert p.entry == pytest.approx(99.95)
    assert advance_position(
        p, pd.Series({"open": 100, "high": 101, "low": 55, "close": 60}), "2025-01-01T02:00Z", cfg
    )
    assert p.pnl > 0
    assert p.exits[0]["price"] == pytest.approx(80 * 1.0005)


def test_next_open_execution_and_no_future_access(features, plan, cfg):
    df = features.tail(4).copy()
    df[["open", "close"]] = 100.0
    df.high = 101.0
    df.low = 99.0
    df.iloc[1, df.columns.get_loc("high")] = 145
    seen = []
    base = analyze(features, cfg)

    def signal(history, settings):
        seen.append(history.index[-1])
        return replace(base, eligible=len(seen) == 1, plan=plan, risk_multiplier=1)

    r = BacktestEngine(cfg).run({}, "1h", start=df.index[0], features=df, signal_fn=signal)
    assert len(r.trades) == 1
    assert pd.Timestamp(r.trades.iloc[0].entry_time) == df.index[1]
    assert r.trades.iloc[0].entry == pytest.approx(100.05)
    assert seen == list(df.index)
    assert r.metrics["fees_paid"] > 0
    assert r.equity.equity.iloc[-1] == pytest.approx(cfg.risk.capital + r.trades.pnl.sum())


def test_monthly_execution_uses_calendar_close_without_false_gap(features, plan, cfg):
    df = features.tail(3).copy()
    df.index = pd.date_range("2024-01-01", periods=3, freq="MS", tz="UTC", name="timestamp")
    df[["open", "close"]] = 100.0
    df.high, df.low = 101.0, 99.0
    df.iloc[1, df.columns.get_loc("high")] = 145
    base = analyze(features, cfg)

    def signal(history, settings):
        return replace(base, eligible=len(history) == 1, plan=plan, risk_multiplier=1)

    result = BacktestEngine(cfg).run({}, "1M", start=df.index[0], features=df, signal_fn=signal)
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert pd.Timestamp(trade.entry_time) == pd.Timestamp("2024-02-01T00:00Z")
    assert pd.Timestamp(trade.exit_time) == pd.Timestamp("2024-03-01T00:00Z")
    assert result.equity.index[-1] == pd.Timestamp("2024-04-01T00:00Z")
    assert all("gap" not in warning.lower() for warning in result.warnings)


def test_risk_protection():
    cfg = RiskConfig()
    guard = RiskGuard(cfg)
    guard.update("2025-01-01T00:00Z", 10000)
    assert guard.update("2025-01-01T12:00Z", 9600)[0] == 0
    assert guard.update("2025-01-02T00:00Z", 9600)[0] == 1
    for _ in range(4):
        guard.record(-1)
    assert guard.update("2025-01-02T01:00Z", 9600)[0] == 0.5
    for _ in range(2):
        guard.record(-1)
    assert guard.update("2025-01-02T02:00Z", 9600)[0] == 0
    guard.reset("2025-01-02T03:00Z", 9600)
    assert guard.update("2025-01-02T04:00Z", 9600)[0] == 1
    assert guard.update("2025-01-02T05:00Z", 8000)[0] == 0


def test_explicit_reset_uses_current_equity():
    guard = RiskGuard(RiskConfig())
    guard.update("2025-01-01T00:00Z", 10000)
    assert guard.update("2025-01-01T01:00Z", 8000)[0] == 0
    guard.reset("2025-01-01T02:00Z", 8000)
    assert guard.update("2025-01-01T03:00Z", 8000)[0] == 1
