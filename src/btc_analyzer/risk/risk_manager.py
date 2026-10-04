"""Drawdown, calendar-period losses, and loss-streak circuit breakers."""

from dataclasses import dataclass
from btc_analyzer.config import RiskConfig
from btc_analyzer.data.base_provider import utc


@dataclass
class RiskGuard:
    config: RiskConfig
    peak: float = 0
    consecutive_losses: int = 0
    paused: bool = False
    day: str = ""
    week: str = ""
    day_start: float = 0
    week_start: float = 0

    def update(self, timestamp: object, equity: float) -> tuple[float, str]:
        """New entries pause on thresholds; existing protective exits always run."""
        t = utc(timestamp)
        day, week = t.strftime("%Y-%m-%d"), f"{t.isocalendar().year}-{t.isocalendar().week}"
        if day != self.day:
            self.day, self.day_start = day, equity
        if week != self.week:
            self.week, self.week_start = week, equity
        self.peak = max(self.peak or self.config.capital, equity)
        dd = 1 - equity / self.peak
        if dd >= self.config.max_drawdown or self.consecutive_losses >= self.config.pause_after_losses:
            self.paused = True  # Latched; explicit reset required, never silently re-enable.
        if self.paused:
            return 0, "Drawdown/streak protection: explicit reset required"
        if self.day_start > 0 and 1 - equity / self.day_start >= self.config.daily_loss_limit:
            return 0, "Daily loss limit"
        if self.week_start > 0 and 1 - equity / self.week_start >= self.config.weekly_loss_limit:
            return 0, "Weekly loss limit"
        if self.consecutive_losses >= self.config.reduce_after_losses:
            return 0.5, "Reduced risk after losses"
        return 1, "Normal risk"

    def record(self, pnl: float) -> None:
        """Increment on a losing completed trade, otherwise reset the streak."""
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

    def reset(self, timestamp: object, equity: float) -> None:
        """User-authorized paper reset uses current equity, not invented recovered profits."""
        self.peak, self.consecutive_losses, self.paused = equity, 0, False
        self.day = self.week = ""
        self.day_start = self.week_start = equity
        self.update(timestamp, equity)
