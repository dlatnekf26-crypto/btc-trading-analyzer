"""Causal price context for a weeks-to-months spot view, not intrinsic valuation."""

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from btc_analyzer.config import AppConfig
from btc_analyzer.strategy.entry_engine import TradePlan


@dataclass(frozen=True)
class PositionView:
    price: float | None
    reference: float | None
    discount_pct: float | None
    drawdown_pct: float | None
    support: float | None
    value_score: float
    stability_score: float
    macro_score: float
    near_support: bool
    falling_fast: bool
    broken_support: bool
    overheated: bool


def _finite(values) -> list[float]:
    return [float(x) for x in values if x is not None and pd.notna(x) and math.isfinite(float(x))]


def price_context(features: dict[str, pd.DataFrame], frames: dict) -> PositionView:
    """Only trailing, already closed data determines discounts and stabilization."""
    macro = 0.6 * frames["1w"].score + 0.4 * frames["1M"].score
    daily = features.get("1d")
    hourly = frames["1h"].indicators
    if daily is None or daily.empty or not frames["1d"].ready or not hourly.get("close"):
        return PositionView(None, None, None, None, None, 0, 0, macro, False, True, False, False)
    row = daily.iloc[-1]
    price, atr = float(hourly["close"]), float(row.atr)
    recent = daily.tail(min(90, int(row.bars_since_gap)))
    reference = float(np.median(_finite(row.get(k) for k in ("ema_50", "ichimoku_kijun", "bb_middle"))))
    discount = 100 * (reference - price) / reference
    peak = float(recent.high.max())
    drawdown = max(0.0, 100 * (peak - price) / peak)
    prior_lows = recent.low.iloc[:-1].tail(20)
    supports = _finite([row.get("last_swing_low"), prior_lows.min()])
    below = [level for level in supports if level <= price]
    support = max(below) if below else min(supports) if supports else None
    near = support is not None and 0 <= (price - support) / atr <= 1.5
    pivot = row.get("last_swing_low")
    broken = pd.notna(pivot) and price < float(pivot) - 0.5 * atr
    three_day_drop = price / float(recent.close.iloc[-4]) - 1 if len(recent) >= 4 else 0
    intraday_drop = price / float(row.close) - 1
    fast = three_day_drop < -max(0.08, 3 * atr / price) or intraday_drop < -max(0.06, 2 * atr / price)

    def improving(frame):
        if frame is None or frame.empty:
            return False
        current = frame.iloc[-1]
        return float(current.rsi_slope) >= 0.1 or float(current.macd_hist_slope) > float(current.atr) * 0.005

    stability = 35 * improving(daily) + 35 * improving(features.get("4h")) + 30 * near
    relative = np.clip(0.5 + (reference - price) / (4 * atr), 0, 1)
    rsi_value = np.clip((70 - float(row.rsi)) / 40, 0, 1)
    correction = np.clip(drawdown / 20, 0, 1)
    value = 100 * (0.4 * relative + 0.25 * rsi_value + 0.2 * correction + 0.15 * near)
    hot = float(row.rsi) >= 72 and price >= reference + 2.5 * atr
    return PositionView(
        price,
        reference,
        discount,
        drawdown,
        support,
        float(value),
        float(stability),
        float(macro),
        bool(near),
        bool(fast),
        bool(broken),
        bool(hot),
    )


def pullback_plan(daily: pd.DataFrame, view: PositionView, cfg: AppConfig) -> TradePlan | None:
    """Bound entries by daily ATR and targets by observed price references."""
    if view.price is None or view.support is None:
        return None
    row = daily.iloc[-1]
    recent = daily.tail(min(90, int(row.bars_since_gap)))
    price, atr = view.price, float(row.atr)
    low, high = price - cfg.strategy.entry_atr_width * atr, price + cfg.strategy.entry_atr_width * atr
    stop = min(view.support, low - atr) - cfg.strategy.atr_buffer * atr
    if stop <= 0 or low <= stop:
        return None
    references = _finite(
        [
            view.reference,
            row.get("ema_50"),
            row.get("ichimoku_kijun"),
            row.get("ichimoku_cloud_a"),
            row.get("ichimoku_cloud_b"),
            row.get("last_swing_high"),
            recent.high.max(),
            *recent.pivot_high.dropna().tolist(),
        ]
    )
    levels = sorted(set(target for target in references if target > high + atr))
    if len(levels) < 3:
        return None
    targets = (levels[0], levels[len(levels) // 2], levels[-1])
    if not targets[0] < targets[1] < targets[2]:
        return None
    risk = price - stop
    return TradePlan(
        "long", low, high, price, stop, targets, tuple((target - price) / risk for target in targets)
    )


def net_ladder_rr(plan: TradePlan | None, cfg: AppConfig) -> float:
    """Conservative RR at the zone's highest entry, including fees and slippage."""
    if plan is None:
        return 0.0
    entry = plan.entry_high * (1 + cfg.risk.slippage)
    exit_stop = plan.stop * (1 - cfg.risk.slippage)
    loss = entry - exit_stop + cfg.risk.fee * (entry + exit_stop)
    if loss <= 0:
        return 0.0
    rewards = [
        target * (1 - cfg.risk.slippage) - entry - cfg.risk.fee * (entry + target * (1 - cfg.risk.slippage))
        for target in plan.targets
    ]
    return float(np.mean(rewards) / loss)
