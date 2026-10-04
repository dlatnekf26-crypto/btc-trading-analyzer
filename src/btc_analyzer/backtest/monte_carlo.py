"""Seeded bootstrap of NET trade R results, with fixed fractional risk approximation."""

import numpy as np
import pandas as pd


def monte_carlo(
    trades: pd.DataFrame,
    initial: float = 10_000,
    risk: float = 0.01,
    simulations: int = 1000,
    seed: int = 42,
    severe_drawdown: float = 0.25,
) -> dict:
    """Bootstrap includes start equity in drawdown. Never infer safety from zero trades.

    This is trade-order/sample uncertainty, not a model of unseen market regimes,
    liquidity, correlations or changing capital caps. Empirical R already includes
    the historical fee/slippage assumptions. At least 1000 simulations are required.
    """
    if simulations < 1000 or initial <= 0 or not 0 < risk <= 0.05 or not 0 < severe_drawdown < 1:
        raise ValueError("Invalid Monte Carlo settings (minimum 1000 simulations)")
    if trades.empty:
        return {"available": False, "reason": "No completed trades", "simulations": simulations}
    values = trades.r_multiple.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite trade R")
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(simulations, len(values)), replace=True)
    factors = np.maximum(1 + risk * draws, 0)
    equity = np.concatenate([np.full((simulations, 1), initial), initial * factors.cumprod(axis=1)], axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    drawdowns = np.max(1 - equity / peak, axis=1)
    streak = np.zeros(simulations, dtype=int)
    worst_streak = np.zeros(simulations, dtype=int)
    for i in range(draws.shape[1]):
        streak = np.where(draws[:, i] < 0, streak + 1, 0)
        worst_streak = np.maximum(streak, worst_streak)
    bands = np.quantile(equity, [0.05, 0.5, 0.95], axis=0)
    return {
        "available": True,
        "trade_count": len(values),
        "evidence_warning": "Fewer than 30 trades: risk estimates have weak evidence"
        if len(values) < 30
        else None,
        "simulations": simulations,
        "seed": seed,
        "expected_drawdown": float(drawdowns.mean()),
        "worst_drawdown": float(drawdowns.max()),
        "drawdown_95": float(np.quantile(drawdowns, 0.95)),
        "severe_drawdown_probability": float((drawdowns >= severe_drawdown).mean()),
        "losing_streak_95": float(np.quantile(worst_streak, 0.95)),
        "worst_losing_streak": int(worst_streak.max()),
        "final_equity_5": float(bands[0, -1]),
        "final_equity_50": float(bands[1, -1]),
        "final_equity_95": float(bands[2, -1]),
        "equity_bands": pd.DataFrame({"p05": bands[0], "median": bands[1], "p95": bands[2]}),
        "drawdowns": drawdowns,
    }
