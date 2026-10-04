"""Shared conservative OHLC fill model used by backtest and paper trading."""

from dataclasses import asdict, dataclass, field
import math
import pandas as pd
from btc_analyzer.config import AppConfig
from btc_analyzer.risk.position_sizing import position_size
from btc_analyzer.strategy.entry_engine import TradePlan


@dataclass
class Position:
    direction: str
    entry_time: str
    signal_time: str
    entry: float
    stop: float
    targets: tuple[float, float, float]
    quantity: float
    risk_amount: float
    regime: str
    volatility: str
    score: float
    quality: float
    remaining: float
    pnl: float
    fees: float
    target_filled: list[bool] = field(default_factory=lambda: [False, False, False])
    exits: list[dict] = field(default_factory=list)

    @property
    def sign(self) -> int:
        return 1 if self.direction == "long" else -1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(**data)

    def equity(self, balance: float, close: float, fee: float) -> float:
        """Liquidation equity includes accrued profit and estimated remaining exit fee."""
        return (
            balance
            + self.pnl
            + self.sign * (close - self.entry) * self.remaining
            - close * self.remaining * fee
        )


def open_position(
    plan: TradePlan,
    timestamp: object,
    signal_time: object,
    opening: float,
    capital: float,
    cfg: AppConfig,
    multiplier: float,
    *,
    regime: str,
    volatility: str,
    score: float,
    quality: float,
) -> Position | None:
    """Candidate expires if next candle OPEN is outside its zone. No retroactive limit fill.

    Cost-adjusted average ladder RR is checked again at the slipped actual entry.
    Paper/backtest short positions are synthetic 1x research exposure only.
    """
    if not plan.entry_low <= opening <= plan.entry_high or multiplier <= 0:
        return None
    sign = 1 if plan.direction == "long" else -1
    entry = opening * (1 + sign * cfg.risk.slippage)
    if sign * (entry - plan.stop) <= 0 or any(sign * (target - entry) <= 0 for target in plan.targets):
        return None
    size = position_size(capital, entry, plan.stop, cfg.risk, multiplier, plan.direction)
    if size.quantity <= 0:
        return None
    unit_risk = size.estimated_loss / size.quantity
    net_rewards = [
        sign * (tp * (1 - sign * cfg.risk.slippage) - entry)
        - cfg.risk.fee * (entry + tp * (1 - sign * cfg.risk.slippage))
        for tp in plan.targets
    ]
    if sum(net_rewards) / (3 * unit_risk) < cfg.strategy.min_rr:
        return None
    entry_fee = entry * size.quantity * cfg.risk.fee
    return Position(
        plan.direction,
        str(timestamp),
        str(signal_time),
        entry,
        plan.stop,
        plan.targets,
        size.quantity,
        size.estimated_loss,
        regime,
        volatility,
        score,
        quality,
        size.quantity,
        -entry_fee,
        entry_fee,
    )


def _exit(
    position: Position, quantity: float, price: float, timestamp: object, reason: str, cfg: AppConfig
) -> None:
    quantity = min(quantity, position.remaining)
    fill = price * (1 - position.sign * cfg.risk.slippage)
    fee = fill * quantity * cfg.risk.fee
    position.pnl += position.sign * (fill - position.entry) * quantity - fee
    position.fees += fee
    position.remaining = max(0, position.remaining - quantity)
    position.exits.append(
        {"time": str(timestamp), "price": fill, "quantity": quantity, "fee": fee, "reason": reason}
    )


def advance_position(
    position: Position, row: pd.Series, timestamp: object, cfg: AppConfig, force: str | None = None
) -> bool:
    """Stops take precedence if stop and targets touch the SAME candle.

    This deliberately conservative convention does not infer unknown intrabar
    paths. Stop gaps fill at the worse opening price. Targets get no favorable
    gap improvement. Stop is fixed across three equal legs; no hidden trailing.
    """
    if force:
        _exit(
            position,
            position.remaining,
            float(row.open if force == "data_gap" else row.close),
            timestamp,
            force,
            cfg,
        )
    else:
        stop_hit = row.low <= position.stop if position.sign == 1 else row.high >= position.stop
        if stop_hit:
            price = (
                min(float(row.open), position.stop)
                if position.sign == 1
                else max(float(row.open), position.stop)
            )
            _exit(position, position.remaining, price, timestamp, "stop", cfg)
        else:
            for i, target in enumerate(position.targets):
                hit = row.high >= target if position.sign == 1 else row.low <= target
                if hit and not position.target_filled[i]:
                    _exit(position, position.quantity / 3, target, timestamp, f"tp{i + 1}", cfg)
                    position.target_filled[i] = True
    return position.remaining <= position.quantity * 1e-10


def completed_trade(position: Position) -> dict:
    """Closed trade audit including exact execution prices and fee ledger."""
    data = position.to_dict()
    exit_time = position.exits[-1]["time"]
    weighted_exit = sum(e["price"] * e["quantity"] for e in position.exits) / position.quantity
    data.update(
        {
            "exit_time": exit_time,
            "exit": weighted_exit,
            "r_multiple": position.pnl / position.risk_amount if position.risk_amount > 0 else 0,
            "result": "win" if position.pnl > 0 else "loss" if position.pnl < 0 else "flat",
            "holding_hours": (pd.Timestamp(exit_time) - pd.Timestamp(position.entry_time)).total_seconds()
            / 3600,
            "exit_reason": position.exits[-1]["reason"],
        }
    )
    if not math.isfinite(data["pnl"]):
        raise ValueError("Nonfinite execution result")
    return data
