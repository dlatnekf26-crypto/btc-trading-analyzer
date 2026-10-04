"""Event-driven next-open engine. Precomputed features must be causal/prefix invariant."""

from collections.abc import Callable
from dataclasses import dataclass
import numpy as np
import pandas as pd
from btc_analyzer.config import AppConfig, TIMEFRAMES
from btc_analyzer.analysis.multi_timeframe import prepare
from btc_analyzer.backtest.execution import open_position, advance_position, completed_trade
from btc_analyzer.backtest.metrics import metrics, regime_metrics
from btc_analyzer.risk.risk_manager import RiskGuard
from btc_analyzer.strategy.signal_engine import Analysis, CooldownGate, analyze


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    metrics: dict
    regimes: pd.DataFrame
    settings: dict
    warnings: list[str]


class BacktestEngine:
    """One 1x position at a time; costs, partial targets, cooldown and risk stops enabled."""

    def __init__(self, cfg: AppConfig | None = None) -> None:
        self.cfg = cfg or AppConfig()

    def run(
        self,
        bundle: dict[str, pd.DataFrame],
        timeframe: str,
        *,
        start: object | None = None,
        end: object | None = None,
        features: pd.DataFrame | None = None,
        signal_fn: Callable[[pd.DataFrame, AppConfig], Analysis] = analyze,
    ) -> BacktestResult:
        """N-close candidate may fill only N+1-open; unfilled candidate expires after one bar."""
        from btc_analyzer.data.base_provider import utc

        cfg = self.cfg
        df = features if features is not None else prepare(bundle, timeframe, cfg)
        if df.empty:
            raise ValueError("Empty backtest data")
        start_time = utc(start) if start is not None else df.index[min(cfg.strategy.warmup_bars, len(df) - 1)]
        end_time = utc(end) if end is not None else df.index[-1] + pd.Timedelta(seconds=TIMEFRAMES[timeframe])
        indices = np.flatnonzero((df.index >= start_time) & (df.index < end_time))
        if len(indices) < 2:
            raise ValueError("At least two evaluation candles required")
        guard, gate = RiskGuard(cfg.risk), CooldownGate(cfg.strategy.cooldown_bars)
        balance, position, pending = cfg.risk.capital, None, None
        ledger, signals, curve = [], [], []
        period = pd.Timedelta(seconds=TIMEFRAMES[timeframe])
        first = df.iloc[indices[0]]
        hold_qty = cfg.risk.capital / (float(first.open) * (1 + cfg.risk.slippage) * (1 + cfg.risk.fee))
        # Include the initial capital point, at evaluation start, before any fills.
        curve.append({"timestamp": df.index[indices[0]], "equity": balance, "buy_hold": balance})
        skipped_gaps = 0
        for ordinal, i in enumerate(indices):
            t, row = df.index[i], df.iloc[i]
            gap = ordinal > 0 and t - df.index[indices[ordinal - 1]] != period
            current_equity = position.equity(balance, float(row.open), cfg.risk.fee) if position else balance
            multiplier, protection = guard.update(t, current_equity)
            if gap:
                pending = None
                skipped_gaps += 1
            if pending and position is None and multiplier > 0:
                a, signal_time = pending
                position = open_position(
                    a.plan,
                    t,
                    signal_time,
                    float(row.open),
                    balance,
                    cfg,
                    multiplier * a.risk_multiplier,
                    regime=a.regime,
                    volatility=a.volatility,
                    score=a.score.overall,
                    quality=a.quality,
                )
            pending = None
            if position is not None:
                if advance_position(
                    position, row, t if gap else t + period, cfg, force="data_gap" if gap else None
                ):
                    trade = completed_trade(position)
                    balance += trade["pnl"]
                    guard.record(trade["pnl"])
                    ledger.append(trade)
                    position = None
            equity = position.equity(balance, float(row.close), cfg.risk.fee) if position else balance
            multiplier, protection = guard.update(t + period, equity)
            window = df.iloc[
                max(0, i - max(cfg.strategy.warmup_bars, cfg.indicators.structure_window) - 10) : i + 1
            ]
            a = signal_fn(window, cfg)
            signature = f"{a.direction}:{a.regime}:{row.structure}"
            permitted = gate.permit(ordinal, a.eligible, signature)
            if position is None and permitted and multiplier > 0 and ordinal < len(indices) - 1:
                pending = (a, t + period)
                gate.fired(ordinal, signature)
                signals.append(
                    {
                        "timestamp": str(t + period),
                        "direction": a.direction,
                        "score": a.score.overall,
                        "quality": a.quality,
                        "regime": a.regime,
                        "entry": a.plan.entry,
                        "stop": a.plan.stop,
                        "targets": a.plan.targets,
                    }
                )
            if ordinal == len(indices) - 1 and position is not None:
                advance_position(position, row, t + period, cfg, force="end_of_test")
                trade = completed_trade(position)
                ledger.append(trade)
                balance += trade["pnl"]
                position, equity = None, balance
            hold = hold_qty * float(row.close) * (1 - cfg.risk.slippage) * (1 - cfg.risk.fee)
            curve.append(
                {"timestamp": t + period, "equity": equity, "buy_hold": hold, "protection": protection}
            )
        trades = pd.DataFrame(ledger)
        curves = pd.DataFrame(curve).set_index("timestamp")
        curves["drawdown"] = curves.equity / curves.equity.cummax() - 1
        warnings = []
        if len(trades) < 30:
            warnings.append("거래 수가 30회 미만입니다. 안정적인 전략 성능을 판단하기에 부족합니다.")
        if skipped_gaps:
            warnings.append(
                f"평가 중 데이터 누락 {skipped_gaps}개: 신규 신호 취소, 기존 포지션은 다음 가용 시가에 보수적으로 청산했습니다."
            )
        summary = metrics(curves.equity, trades, cfg.risk.capital)
        summary["buy_hold_return"] = float(curves.buy_hold.iloc[-1] / cfg.risk.capital - 1)
        return BacktestResult(
            curves,
            trades,
            pd.DataFrame(signals),
            summary,
            regime_metrics(trades, cfg.risk.capital),
            cfg.to_dict(),
            warnings,
        )
