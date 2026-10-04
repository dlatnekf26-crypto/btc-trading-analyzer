"""Sensitivity, cost replay, disjoint holdout and conservative evidence-based classification."""

from dataclasses import replace
from itertools import product
import pandas as pd
from btc_analyzer.analysis.multi_timeframe import prepare
from btc_analyzer.backtest.engine import BacktestEngine, BacktestResult
from btc_analyzer.backtest.monte_carlo import monte_carlo
from btc_analyzer.backtest.walk_forward import split_evaluation
from btc_analyzer.config import AppConfig


def sensitivity(
    bundle: dict[str, pd.DataFrame],
    timeframe: str,
    cfg: AppConfig,
    start: object | None = None,
    rsi_periods: tuple[int, ...] = (12, 14, 16),
    ema_periods: tuple[int, ...] = (18, 20, 22),
    atr_buffers: tuple[float, ...] = (0.3, 0.5, 0.7),
) -> pd.DataFrame:
    """Explore a neighborhood on IN-SAMPLE ONLY. No selection on final test data.

    Extra EMA periods extend the arrangement set; default benchmark periods are
    retained. Slopes use the selected fast_trend_length so the period actually
    changes the strategy rather than producing a decorative parameter grid.
    """
    rows = []
    for rsi_period, ema_period in product(rsi_periods, ema_periods):
        lengths = tuple(sorted(set((*cfg.indicators.ema_lengths, ema_period))))
        icfg = replace(
            cfg.indicators, rsi_length=rsi_period, ema_lengths=lengths, fast_trend_length=ema_period
        )
        base = replace(cfg, indicators=icfg)
        features = prepare(bundle, timeframe, base)
        from btc_analyzer.backtest.walk_forward import evaluation_bounds

        index = evaluation_bounds(features, cfg, start)
        cutoff = index[max(1, int(len(index) * 0.6))]
        for buffer in atr_buffers:
            candidate = replace(base, strategy=replace(base.strategy, atr_buffer=buffer))
            r = BacktestEngine(candidate).run(
                bundle, timeframe, start=index[0], end=cutoff, features=features
            )
            rows.append(
                {
                    "rsi": rsi_period,
                    "ema": ema_period,
                    "atr_buffer": buffer,
                    "return": r.metrics["total_return"],
                    "sharpe": r.metrics["sharpe"],
                    "mdd": r.metrics["maximum_drawdown"],
                    "trades": r.metrics["number_of_trades"],
                    "expectancy": r.metrics["expectancy"],
                    "evaluation": "In-Sample only",
                }
            )
    return pd.DataFrame(rows)


def cost_stress(
    bundle: dict[str, pd.DataFrame], timeframe: str, cfg: AppConfig, start: object | None = None
) -> pd.DataFrame:
    """Re-execute (not merely subtract fees) because costs change sizing and eligible fills."""
    rows = []
    features = prepare(bundle, timeframe, cfg)
    for factor in (1.0, 1.5, 2.0):
        candidate = replace(
            cfg, risk=replace(cfg.risk, fee=cfg.risk.fee * factor, slippage=cfg.risk.slippage * factor)
        )
        result = BacktestEngine(candidate).run(bundle, timeframe, start=start, features=features)
        rows.append(
            {
                "cost_multiplier": factor,
                "return": result.metrics["total_return"],
                "expectancy": result.metrics["expectancy"],
                "trades": result.metrics["number_of_trades"],
                "mdd": result.metrics["maximum_drawdown"],
                "sharpe": result.metrics["sharpe"],
            }
        )
    return pd.DataFrame(rows)


def assess(
    base: BacktestResult,
    splits: dict[str, BacktestResult],
    parameter_results: pd.DataFrame,
    simulation: dict,
    costs: pd.DataFrame,
    walk: pd.DataFrame | None = None,
) -> dict:
    """Do not award Production Candidate on tiny samples or missing evaluations.

    Classification is a research screening rubric, not authorization for live
    orders, a promise of profits or statistical proof of future generalization.
    """
    oos = splits["Out-of-Sample"].metrics
    ins = splits["In-Sample"].metrics
    enough = oos["number_of_trades"] >= 30
    oos_pass = (
        enough and (oos["expectancy"] or 0) > 0 and (oos["sharpe"] or 0) > 0 and oos["maximum_drawdown"] < 0.2
    )
    status = "Pass" if oos_pass else "Warning" if not enough else "Fail"
    credible_params = (
        parameter_results[parameter_results.trades >= 5] if not parameter_results.empty else parameter_results
    )
    stability_ratio = float((credible_params.expectancy > 0).mean()) if len(credible_params) else 0
    stable = len(credible_params) >= max(3, len(parameter_results) * 0.7) and stability_ratio >= 0.7
    cost_pass = len(costs) == 3 and bool(((costs.trades >= 5) & (costs.expectancy > 0)).all())
    mc_available = simulation.get("available", False) and base.metrics["number_of_trades"] >= 30
    mc_probability = simulation.get("severe_drawdown_probability", 1)
    mc_risk = (
        "Low"
        if mc_available and mc_probability < 0.05
        else "Medium"
        if mc_available and mc_probability < 0.2
        else "High"
    )
    cohorts = base.regimes[base.regimes.trades >= 5] if not base.regimes.empty else base.regimes
    regime_score = float((cohorts["return"] > 0).mean() * 100) if len(cohorts) else 0
    # Unobserved regimes cannot earn full coverage credit.
    regime_score *= min(1, len(cohorts) / 3)
    degradation = ins["total_return"] > 0 and oos["total_return"] < 0
    overfit = (
        "High" if not enough or not stable or degradation else "Low" if oos_pass and cost_pass else "Medium"
    )
    walk_pass = bool(
        walk is not None
        and len(walk) >= 3
        and (walk.test_trades >= 5).all()
        and (~walk.validation_veto).mean() >= 0.6
        and (walk.approved_test_return > 0).mean() >= 0.6
    )
    score = (
        30 * oos_pass
        + 20 * stable
        + 15 * cost_pass
        + 15 * (mc_risk == "Low")
        + 0.1 * regime_score
        + 10 * walk_pass
    )
    classification = (
        "Production Candidate"
        if score >= 80 and enough and overfit == "Low"
        else (
            "Rejected"
            if status == "Fail" or (enough and not cost_pass and (oos["expectancy"] or 0) < 0)
            else "Needs Improvement"
        )
    )
    return {
        "robustness_score": round(score, 1),
        "overfitting_risk": overfit,
        "out_of_sample": status,
        "parameter_stability": "Stable" if stable else "Unstable",
        "monte_carlo_risk": mc_risk,
        "trading_cost_robustness": "Pass" if cost_pass else "Fail",
        "regime_robustness": round(regime_score, 1),
        "walk_forward": "Pass" if walk_pass else "Warning",
        "final_classification": classification,
        "live_orders_enabled": False,
        "evidence_note": "OOS≥30 trades; sensitivity is IS-only. Unobserved regimes/sample shortage reduce confidence.",
    }


def run_robustness(
    bundle: dict[str, pd.DataFrame],
    timeframe: str,
    cfg: AppConfig,
    start: object | None = None,
    simulations: int = 1000,
    seed: int = 42,
    compact: bool = False,
) -> dict:
    """Full workflow; compact uses a 3-point ATR neighborhood for quick UI/tests."""
    from btc_analyzer.backtest.walk_forward import walk_forward

    base = BacktestEngine(cfg).run(bundle, timeframe, start=start)
    splits = split_evaluation(bundle, timeframe, cfg, start=start)
    parameters = sensitivity(
        bundle,
        timeframe,
        cfg,
        start=start,
        rsi_periods=(cfg.indicators.rsi_length,) if compact else (12, 14, 16),
        ema_periods=(20,) if compact else (18, 20, 22),
    )
    simulation = monte_carlo(base.trades, cfg.risk.capital, cfg.risk.risk_fraction, simulations, seed)
    costs = cost_stress(bundle, timeframe, cfg, start)
    from btc_analyzer.backtest.walk_forward import evaluation_bounds

    index = evaluation_bounds(prepare(bundle, timeframe, cfg), cfg, start)
    train, validation, test = max(10, len(index) // 3), max(10, len(index) // 9), max(10, len(index) // 9)
    walk = (
        walk_forward(bundle, timeframe, cfg, start, train, validation, test)
        if len(index) >= train + validation + test
        else pd.DataFrame()
    )
    return {
        "base": base,
        "splits": splits,
        "parameters": parameters,
        "simulation": simulation,
        "costs": costs,
        "walk_forward": walk,
        "assessment": assess(base, splits, parameters, simulation, costs, walk),
    }
