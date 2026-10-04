"""ATR-sized clusters of recent confirmed reactions and moving-average references."""

from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Zone:
    low: float
    high: float
    kind: str
    strength: int

    @property
    def center(self) -> float:
        return (self.low + self.high) / 2

    def to_dict(self) -> dict:
        return asdict(self)


def zones(history: pd.DataFrame, max_each: int = 3, lookback: int = 120) -> list[Zone]:
    """Cluster only information available in history; bound the number of plotted zones."""
    row = history.iloc[-1]
    price, atr = float(row.close), float(row.atr)
    if not np.isfinite(atr) or atr <= 0:
        return []
    width = max(atr * 0.3, price * 0.0005)
    recent = history.tail(min(lookback, int(row.bars_since_gap)))
    points = list(recent.pivot_high.dropna()) + list(recent.pivot_low.dropna())
    points += [float(row[k]) for k in ("ema_20", "ema_50", "sma_20", "bb_middle") if np.isfinite(row[k])]
    clusters: list[list[float]] = []
    for point in sorted(points):
        if clusters and point - np.mean(clusters[-1]) <= width:
            clusters[-1].append(point)
        else:
            clusters.append([point])
    result = [
        Zone(
            float(np.mean(c) - width / 2),
            float(np.mean(c) + width / 2),
            "Support" if np.mean(c) < price else "Resistance",
            len(c),
        )
        for c in clusters
    ]
    selected = []
    for kind in ("Support", "Resistance"):
        ranked = sorted(
            [z for z in result if z.kind == kind],
            key=lambda z: abs(z.center - price) / (1 + min(z.strength, 5) * 0.15),
        )
        selected.extend(ranked[:max_each])
    return selected
