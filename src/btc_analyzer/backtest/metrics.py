"""Risk-adjusted performance with calendar-time daily returns for 24/7 crypto."""

import numpy as np
import pandas as pd


def metrics(equity: pd.Series, trades: pd.DataFrame, initial: float) -> dict:
    """Unavailable ratios are None, never invented as zero/infinite success.

    Sharpe/Sortino use daily closing-equity returns and sqrt(365). Sub-day
    histories cannot estimate them. CAGR is only reported for >=30 days to
    avoid absurd annualization of tiny samples. Risk-free rate defaults to zero.
    """
    final = float(equity.iloc[-1]) if len(equity) else initial
    duration = (equity.index[-1] - equity.index[0]).total_seconds() / 86400 if len(equity) > 1 else 0
    growth = final / initial - 1
    cagr = float((final / initial) ** (365 / duration) - 1) if duration >= 30 and final > 0 else None
    peak = equity.cummax().clip(lower=initial)
    dd = (equity / peak - 1) if len(equity) else pd.Series(dtype=float)
    mdd = float(-dd.min()) if len(dd) else 0.0
    daily = equity.resample("1D").last().dropna() if len(equity) else pd.Series(dtype=float)
    returns = daily.pct_change(fill_method=None).dropna()
    std = returns.std(ddof=1)
    sharpe = float(returns.mean() / std * np.sqrt(365)) if len(returns) >= 2 and std > 0 else None
    downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2)) if len(returns) >= 2 else 0
    sortino = float(returns.mean() / downside * np.sqrt(365)) if downside > 0 else None
    pnls = trades.pnl.to_numpy() if not trades.empty else np.array([])
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    return {
        "initial_capital": initial,
        "final_capital": final,
        "total_return": growth,
        "cagr": cagr,
        "win_rate": len(wins) / len(pnls) if len(pnls) else None,
        "loss_rate": len(losses) / len(pnls) if len(pnls) else None,
        "number_of_trades": len(pnls),
        "average_win": float(wins.mean()) if len(wins) else None,
        "average_loss": float(losses.mean()) if len(losses) else None,
        "average_r": float(trades.r_multiple.mean()) if not trades.empty else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "expectancy": float(pnls.mean()) if len(pnls) else None,
        "maximum_drawdown": mdd,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": cagr / mdd if cagr is not None and mdd > 0 else None,
        "recovery_factor": (final - initial) / (initial * mdd) if mdd > 0 else None,
        "average_holding_hours": float(trades.holding_hours.mean()) if not trades.empty else None,
        "fees_paid": float(trades.fees.sum()) if not trades.empty else 0,
        "sample_days": duration,
        "insufficient_trades": len(pnls) < 30,
    }


def regime_metrics(trades: pd.DataFrame, initial: float) -> pd.DataFrame:
    """Entry-regime trade cohorts (not full calendar portfolios); label this distinction in UI."""
    rows = []
    if trades.empty:
        return pd.DataFrame(columns=["regime", "return", "win_rate", "profit_factor", "mdd", "trades"])
    groups = {
        "Bull Market": trades[trades.regime.str.contains("Uptrend")],
        "Bear Market": trades[trades.regime.str.contains("Downtrend")],
        "Sideways": trades[trades.regime == "Sideways"],
        "High Volatility": trades[trades.volatility.isin(["High Volatility", "Extreme Volatility"])],
        "Low Volatility": trades[trades.volatility == "Low Volatility"],
    }
    for name, cohort in groups.items():
        if cohort.empty:
            rows.append(
                {
                    "regime": name,
                    "return": None,
                    "win_rate": None,
                    "profit_factor": None,
                    "mdd": None,
                    "trades": 0,
                }
            )
            continue
        p = cohort.sort_values("exit_time").pnl
        curve = pd.concat([pd.Series([initial]), initial + p.cumsum()], ignore_index=True)
        losses = -p[p < 0].sum()
        rows.append(
            {
                "regime": name,
                "return": float(p.sum() / initial),
                "win_rate": float((p > 0).mean()),
                "profit_factor": float(p[p > 0].sum() / losses) if losses > 0 else None,
                "mdd": float(-(curve / curve.cummax() - 1).min()),
                "trades": len(cohort),
            }
        )
    return pd.DataFrame(rows)
