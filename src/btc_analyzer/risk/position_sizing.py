"""1x capital/risk caps, including entry+exit fees and adverse stop slippage."""

from dataclasses import dataclass
import math
from btc_analyzer.config import RiskConfig


@dataclass(frozen=True)
class PositionSize:
    quantity: float
    risk_budget: float
    estimated_loss: float
    notional: float


def position_size(
    capital: float, entry: float, stop: float, cfg: RiskConfig, multiplier: float = 1, direction: str = "long"
) -> PositionSize:
    """Entry is the expected/actual fill. Cap notional including entry fee to available cash."""
    if direction not in ("long", "short") or not all(
        math.isfinite(x) for x in (capital, entry, stop, multiplier)
    ):
        raise ValueError("Invalid sizing inputs")
    if min(entry, stop) <= 0 or capital < 0 or not 0 <= multiplier <= 1:
        raise ValueError("Prices must be positive and risk multiplier in [0,1]")
    sign = 1 if direction == "long" else -1
    if sign * (entry - stop) <= 0:
        raise ValueError("Stop must lie on the loss side of entry")
    stop_fill = stop * (1 - sign * cfg.slippage)
    per_unit = abs(entry - stop_fill) + cfg.fee * (entry + stop_fill)
    budget = capital * cfg.risk_fraction * multiplier
    quantity = min(budget / per_unit, capital / (entry * (1 + cfg.fee))) if capital > 0 else 0.0
    return PositionSize(quantity, budget, quantity * per_unit, quantity * entry)
