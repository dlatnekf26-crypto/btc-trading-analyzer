"""Chronological splits and train-only candidate selection; OOS never tunes parameters."""

from dataclasses import replace
import numpy as np
import pandas as pd
from btc_analyzer.analysis.multi_timeframe import prepare
from btc_analyzer.backtest.engine import BacktestEngine, BacktestResult
from btc_analyzer.config import AppConfig
from btc_analyzer.candles import candle_close


def objective(result: BacktestResult) -> float:
    """Reward risk-adjusted return and evidence; penalize drawdown and low sample count."""
    m = result.metrics
    if m["number_of_trades"] < 5:
        return -100.0 + m["number_of_trades"]
    return float(
        (m["sharpe"] or 0)
        + min(m["profit_factor"] or 0, 5) * 0.2
        + np.tanh(m["total_return"] * 5)
        - m["maximum_drawdown"] * 5
    )


def evaluation_bounds(
    features: pd.DataFrame, cfg: AppConfig, start: object | None = None
) -> pd.DatetimeIndex:
    """Exclude indicator warmup or use the user's explicit evaluation boundary."""
    from btc_analyzer.data.base_provider import utc

    threshold = (
        utc(start) if start is not None else features.index[min(cfg.strategy.warmup_bars, len(features) - 1)]
    )
    return features.index[features.index >= threshold]


def split_evaluation(
    bundle: dict[str, pd.DataFrame],
    timeframe: str,
    cfg: AppConfig,
    start: object | None = None,
    fractions: tuple[float, float, float] = (0.6, 0.2, 0.2),
) -> dict[str, BacktestResult]:
    """Same FIXED strategy on disjoint 60/20/20 periods, each starting with fresh capital.

    Historical warmup before a test boundary is allowed. Each period closes its
    own positions at its end and cannot carry a trained position into OOS.
    """
    if len(fractions) != 3 or min(fractions) <= 0 or not np.isclose(sum(fractions), 1):
        raise ValueError("Three positive split fractions must sum to one")
    features = prepare(bundle, timeframe, cfg)
    index = evaluation_bounds(features, cfg, start)
    if len(index) < 30:
        raise ValueError("Need at least 30 evaluation bars to split")
    boundaries = [0, int(len(index) * fractions[0]), int(len(index) * sum(fractions[:2])), len(index)]
    results = {}
    for j, label in enumerate(("In-Sample", "Validation", "Out-of-Sample")):
        a, b = boundaries[j : j + 2]
        results[label] = BacktestEngine(cfg).run(
            bundle, timeframe, start=index[a], end=candle_close(index[b - 1], timeframe), features=features
        )
    return results


def walk_forward(
    bundle: dict[str, pd.DataFrame],
    timeframe: str,
    cfg: AppConfig,
    start: object | None = None,
    train_bars: int = 240,
    validation_bars: int = 80,
    test_bars: int = 80,
    candidates: list[AppConfig] | None = None,
) -> pd.DataFrame:
    """Rolling train/validate/test. Pick on train, veto on validation, record untouched test.

    Test windows do not overlap. Windows need not yield trades; no-trade folds
    remain visible instead of being dropped. This reports folds, not an inflated
    stitched portfolio which restarts with new capital on every fold.
    """
    if min(train_bars, validation_bars, test_bars) < 10:
        raise ValueError("Walk-forward windows must have at least 10 bars")
    candidates = candidates or [
        replace(cfg, strategy=replace(cfg.strategy, min_score=s)) for s in (60.0, 65.0, 70.0)
    ]
    prepared = [prepare(bundle, timeframe, candidate) for candidate in candidates]
    index = evaluation_bounds(prepared[0], cfg, start)
    total = train_bars + validation_bars + test_bars
    if len(index) < total:
        raise ValueError(f"Need {total} evaluation bars for one complete walk-forward fold")
    rows = []
    for offset in range(0, len(index) - total + 1, test_bars):
        train_end = offset + train_bars
        val_end = train_end + validation_bars
        test_end = val_end + test_bars
        training = [
            BacktestEngine(c).run(
                bundle,
                timeframe,
                start=index[offset],
                end=candle_close(index[train_end - 1], timeframe),
                features=f,
            )
            for c, f in zip(candidates, prepared)
        ]
        chosen = int(np.argmax([objective(r) for r in training]))
        candidate, features = candidates[chosen], prepared[chosen]
        validation = BacktestEngine(candidate).run(
            bundle,
            timeframe,
            start=index[train_end],
            end=candle_close(index[val_end - 1], timeframe),
            features=features,
        )
        test = BacktestEngine(candidate).run(
            bundle,
            timeframe,
            start=index[val_end],
            end=candle_close(index[test_end - 1], timeframe),
            features=features,
        )
        veto = validation.metrics["number_of_trades"] < 5 or (validation.metrics["expectancy"] or 0) <= 0
        rows.append(
            {
                "fold": len(rows) + 1,
                "train_start": str(index[offset]),
                "train_end": str(candle_close(index[train_end - 1], timeframe)),
                "validation_start": str(index[train_end]),
                "test_start": str(index[val_end]),
                "test_end": str(candle_close(index[test_end - 1], timeframe)),
                "selected_settings": candidate.to_dict(),
                "train_objective": objective(training[chosen]),
                "validation_return": validation.metrics["total_return"],
                "validation_trades": validation.metrics["number_of_trades"],
                "validation_veto": veto,
                "test_return": test.metrics["total_return"],
                "test_trades": test.metrics["number_of_trades"],
                "test_sharpe": test.metrics["sharpe"],
                "test_mdd": test.metrics["maximum_drawdown"],
                "approved_test_return": 0.0 if veto else test.metrics["total_return"],
            }
        )
    return pd.DataFrame(rows)
