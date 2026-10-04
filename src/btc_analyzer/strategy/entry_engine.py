"""Symmetric pullback zones, structural stops and three resistance-aware targets."""

from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd
from btc_analyzer.analysis.support_resistance import Zone
from btc_analyzer.config import StrategyConfig


@dataclass(frozen=True)
class TradePlan:
    direction: str
    entry_low: float
    entry_high: float
    entry: float
    stop: float
    targets: tuple[float, float, float]
    rr: tuple[float, float, float]

    @property
    def effective_rr(self) -> float:
        """Equal-size, three-target ladder gross R; execution rechecks costs and actual entry."""
        return float(np.mean(self.rr))

    def to_dict(self) -> dict:
        return asdict(self)


def entry_plan(
    row: pd.Series, levels: list[Zone], direction: str, cfg: StrategyConfig | None = None
) -> TradePlan | None:
    """Prefer the nearest pullback reference; never place a stop on the profitable side."""
    cfg = cfg or StrategyConfig()
    if direction not in ("long", "short"):
        raise ValueError("Direction must be long/short")
    price, atr = float(row.close), float(row.atr)
    if not np.isfinite(atr) or atr <= 0:
        return None
    sign = 1 if direction == "long" else -1
    kind = "Support" if sign == 1 else "Resistance"
    references = [z.center for z in levels if z.kind == kind and sign * (price - z.center) >= 0]
    references += [
        float(row[k])
        for k in ("ema_20", "ema_50", "bb_middle")
        if np.isfinite(row[k]) and sign * (price - row[k]) >= 0
    ]
    anchor = min(references, key=lambda x: abs(price - x)) if references else price - sign * atr * 0.5
    low, high = max(anchor - cfg.entry_atr_width * atr, price * 0.01), anchor + cfg.entry_atr_width * atr
    entry = (low + high) / 2
    swing_name = "last_swing_low" if sign == 1 else "last_swing_high"
    swing = row.get(swing_name, np.nan)
    if not np.isfinite(swing) or sign * (entry - swing) <= 0:
        swing = entry - sign * atr * 1.5
    stop = float(swing - sign * atr * cfg.atr_buffer)
    if stop <= 0:
        return None
    risk = sign * (entry - stop)
    if risk <= 0:
        return None
    opposite = "Resistance" if sign == 1 else "Support"
    distances = [sign * (z.center - entry) for z in levels if z.kind == opposite]
    band = row.get("bb_upper" if sign == 1 else "bb_lower", np.nan)
    if np.isfinite(band):
        distances.append(sign * (band - entry))
    distances = sorted(d for d in distances if d > atr * 0.2)
    tp1 = min(distances[0], risk * 1.5) if distances else risk * 1.5
    tp2 = max(tp1 + atr * 0.3, min(distances[1], risk * 2) if len(distances) > 1 else risk * 2)
    tp3 = max(tp2 + atr * 0.5, risk * 3)
    targets = tuple(float(entry + sign * distance) for distance in (tp1, tp2, tp3))
    if min(targets) <= 0:
        return None
    return TradePlan(
        direction,
        float(low),
        float(high),
        float(entry),
        stop,
        targets,
        tuple(float(distance / risk) for distance in (tp1, tp2, tp3)),
    )
