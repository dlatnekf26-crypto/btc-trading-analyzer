"""Validated, serializable settings; all capital is in the selected quote currency."""

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path

# Month seconds are a nominal length for ordering/weights ONLY. Candle closure,
# pagination and gaps use calendar-aware helpers in candles.py.
TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800, "1M": 2592000}
COMPOSITE_TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")
MTF_MAP = {
    "5m": ("5m", "15m", "1h", "1d"),
    "15m": ("5m", "15m", "1h", "1d"),
    "1h": ("15m", "1h", "4h", "1d"),
    "4h": ("1h", "4h", "1d"),
    "1d": ("4h", "1d"),
    "1w": ("1d", "1w", "1M"),
    "1M": ("1w", "1M"),
}


@dataclass(frozen=True)
class IndicatorConfig:
    ema_lengths: tuple[int, ...] = (9, 20, 50, 100, 200)
    sma_lengths: tuple[int, ...] = (20, 60, 120, 200)
    fast_trend_length: int = 20
    rsi_length: int = 14
    atr_length: int = 14
    bb_length: int = 20
    bb_std: float = 2.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_length: int = 20
    slope_length: int = 3
    pivot_left: int = 3
    pivot_right: int = 3
    structure_window: int = 120

    def __post_init__(self) -> None:
        lengths = [
            *self.ema_lengths,
            *self.sma_lengths,
            self.rsi_length,
            self.atr_length,
            self.bb_length,
            self.macd_fast,
            self.macd_slow,
            self.macd_signal,
            self.volume_length,
            self.fast_trend_length,
            self.slope_length,
            self.pivot_left,
            self.pivot_right,
            self.structure_window,
        ]
        if any(not isinstance(x, int) or x < 1 for x in lengths):
            raise ValueError("Indicator periods must be positive integers")
        if not math.isfinite(self.bb_std) or self.bb_std <= 0 or self.macd_fast >= self.macd_slow:
            raise ValueError("Invalid Bollinger or MACD settings")
        if self.fast_trend_length not in self.ema_lengths:
            raise ValueError("Fast trend EMA must be available")
        if not {9, 20, 50, 100, 200}.issubset(self.ema_lengths):
            raise ValueError("Default EMA periods must remain available")
        if not {20, 60, 120, 200}.issubset(self.sma_lengths):
            raise ValueError("Default SMA periods must remain available")


@dataclass(frozen=True)
class StrategyConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "trend": 0.35,
            "momentum": 0.25,
            "volume": 0.20,
            "volatility": 0.10,
            "structure": 0.10,
        }
    )
    min_score: float = 65.0
    min_quality: float = 75.0
    min_rr: float = 1.5
    target_rr: float = 2.0
    atr_buffer: float = 0.5
    entry_atr_width: float = 0.25
    cooldown_bars: int = 12
    warmup_bars: int = 210
    allow_short: bool = False  # Research/paper only; spot mode defaults to long-only.
    disabled_regimes: tuple[str, ...] = ("Strong Downtrend",)
    regime_risk: dict[str, float] = field(default_factory=lambda: {"Sideways": 0.5, "Downtrend": 0.5})

    def __post_init__(self) -> None:
        if set(self.weights) != {"trend", "momentum", "volume", "volatility", "structure"}:
            raise ValueError("Five score weights are required")
        if (
            any(not math.isfinite(v) or v < 0 for v in self.weights.values())
            or sum(self.weights.values()) <= 0
        ):
            raise ValueError("Weights must be finite, nonnegative and have a positive sum")
        if not 50 <= self.min_score <= 100 or not 0 <= self.min_quality <= 100:
            raise ValueError("Invalid signal thresholds")
        if not all(
            math.isfinite(x) and x > 0
            for x in (self.min_rr, self.target_rr, self.atr_buffer, self.entry_atr_width)
        ):
            raise ValueError("RR and ATR multipliers must be positive")
        if self.cooldown_bars < 0 or self.warmup_bars < 200:
            raise ValueError("Require at least 200 warmup bars and nonnegative cooldown")
        if any(not math.isfinite(x) or not 0 <= x <= 1 for x in self.regime_risk.values()):
            raise ValueError("Regime risk multipliers must be in [0,1]")


@dataclass(frozen=True)
class RiskConfig:
    capital: float = 10_000.0
    risk_fraction: float = 0.01
    fee: float = 0.001
    slippage: float = 0.0005
    leverage: float = 1.0
    daily_loss_limit: float = 0.03
    weekly_loss_limit: float = 0.06
    max_drawdown: float = 0.15
    reduce_after_losses: int = 4
    pause_after_losses: int = 6

    def __post_init__(self) -> None:
        if not math.isfinite(self.capital) or self.capital <= 0:
            raise ValueError("Capital must be positive")
        if not math.isfinite(self.risk_fraction) or not 0 < self.risk_fraction <= 0.05:
            raise ValueError("Account risk must be between 0 and 5%")
        if self.leverage != 1:
            raise ValueError("V1 supports 1x only")
        if any(not math.isfinite(x) or not 0 <= x < 1 for x in (self.fee, self.slippage)):
            raise ValueError("Fee/slippage must be between 0 and 1")
        if any(
            not math.isfinite(x) or not 0 < x < 1
            for x in (self.daily_loss_limit, self.weekly_loss_limit, self.max_drawdown)
        ):
            raise ValueError("Loss limits must be between 0 and 1")
        if not 0 < self.reduce_after_losses < self.pause_after_losses:
            raise ValueError("Loss reduction must precede pause")


@dataclass(frozen=True)
class AppConfig:
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    def to_dict(self) -> dict:
        """Return JSON-safe settings suitable for SQLite audit records."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "AppConfig":
        """Validate uploaded JSON before constructing complete or partial settings.

        Reject misspelled sections rather than silently substituting defaults.
        Invalid JSON shapes/types become ValueError, which the dashboard handles
        as a user-facing validation error instead of an application exception.
        """
        if not isinstance(data, dict):
            raise ValueError("Settings must be a JSON object")
        constructors = {
            "indicators": IndicatorConfig,
            "strategy": StrategyConfig,
            "risk": RiskConfig,
        }
        unknown = set(data) - set(constructors)
        if unknown:
            raise ValueError(f"Unknown settings sections: {', '.join(sorted(map(str, unknown)))}")
        validated = {}
        for section, constructor in constructors.items():
            values = data.get(section, {})
            if not isinstance(values, dict):
                raise ValueError(f"{section} settings must be a JSON object")
            try:
                validated[section] = constructor(**values)
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError(f"Invalid {section} settings: {exc}") from exc
        return cls(**validated)

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        """Read non-secret JSON configuration."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
