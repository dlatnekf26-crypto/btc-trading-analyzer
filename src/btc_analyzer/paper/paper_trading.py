"""Persistent virtual-only engine. Advances only CLOSED candles, once per account."""

from dataclasses import asdict
import hashlib
import json
import pandas as pd
from btc_analyzer.backtest.execution import Position, open_position, advance_position, completed_trade
from btc_analyzer.config import AppConfig
from btc_analyzer.candles import candle_close
from btc_analyzer.data.base_provider import utc
from btc_analyzer.risk.risk_manager import RiskGuard
from btc_analyzer.storage.database import Database, dumps
from btc_analyzer.strategy.entry_engine import TradePlan
from btc_analyzer.strategy.signal_engine import CooldownGate, analyze


class PaperTrader:
    """The first tick records a baseline, not invented historical fills.

    On later ticks missed closed candles are processed chronologically. Live and
    synthetic data and changed settings create isolated accounts. State, fills,
    protective pause and cooldown survive Streamlit reruns and process restarts.
    """

    def __init__(
        self, db: Database, cfg: AppConfig, exchange: str, symbol: str, timeframe: str, source: str = "live"
    ) -> None:
        self.db, self.cfg = db, cfg
        self.exchange, self.symbol, self.timeframe, self.source = exchange, symbol, timeframe, source
        self.strategy_key = hashlib.sha256(dumps(cfg.to_dict()).encode()).hexdigest()[:16]
        self.account = f"{source}:{exchange}:{symbol}:{timeframe}:{self.strategy_key}"

    def _initial(self) -> dict:
        return {
            "balance": self.cfg.risk.capital,
            "position": None,
            "pending": None,
            "last_bar": None,
            "ordinal": 0,
            "enabled": False,
            "guard": asdict(RiskGuard(self.cfg.risk)),
            "gate": asdict(CooldownGate(self.cfg.strategy.cooldown_bars)),
            "protection": "Normal risk",
        }

    def state(self) -> dict:
        with self.db.connect() as conn:
            record = conn.execute(
                "SELECT state FROM paper_accounts WHERE account=?", (self.account,)
            ).fetchone()
        return json.loads(record[0]) if record else self._initial()

    def _save_trade(self, conn: object, position: Position, closed: bool) -> None:
        trade = completed_trade(position) if closed else position.to_dict()
        result = trade["result"] if closed else "open"
        conn.execute(
            "INSERT INTO paper_trades(account,timestamp,exchange,symbol,timeframe,data_source,direction,entry,stop,tp,position_size,result,pnl,r_multiple,signal_score,regime,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account,timestamp) DO UPDATE SET result=excluded.result,pnl=excluded.pnl,r_multiple=excluded.r_multiple,payload=excluded.payload",
            (
                self.account,
                position.signal_time,
                self.exchange,
                self.symbol,
                self.timeframe,
                self.source,
                position.direction,
                position.entry,
                position.stop,
                dumps(position.targets),
                position.quantity,
                result,
                position.pnl,
                trade.get("r_multiple"),
                position.score,
                position.regime,
                dumps(trade),
            ),
        )

    def tick(self, features: pd.DataFrame, now: object | None = None, allow_new_entries: bool = True) -> dict:
        """Only process candles that have actually closed by now; transaction is idempotent."""
        now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
        features = features.loc[candle_close(features.index, self.timeframe) <= now]
        if features.empty:
            raise ValueError("Paper trading needs closed candles")
        with self.db.connect(write=True) as conn:
            record = conn.execute(
                "SELECT state FROM paper_accounts WHERE account=?", (self.account,)
            ).fetchone()
            state = json.loads(record[0]) if record else self._initial()
            guard_data = dict(state["guard"])
            guard_data.pop("config", None)
            guard = RiskGuard(self.cfg.risk, **guard_data)
            gate = CooldownGate(**state["gate"])
            position = Position.from_dict(state["position"]) if state["position"] else None
            if state["last_bar"] is None:
                indices = [len(features) - 1]  # First activation only sees latest closed signal.
            else:
                indices = [i for i, t in enumerate(features.index) if t > utc(state["last_bar"])]
            for i in indices:
                t, row = features.index[i], features.iloc[i]
                closed_at = candle_close(t, self.timeframe)
                gap = state["last_bar"] is not None and t != candle_close(
                    utc(state["last_bar"]), self.timeframe
                )
                equity = (
                    position.equity(state["balance"], float(row.open), self.cfg.risk.fee)
                    if position
                    else state["balance"]
                )
                multiplier, state["protection"] = guard.update(t, equity)
                pending = state["pending"]
                if pending and position is None and not gap and multiplier > 0 and allow_new_entries:
                    plan = TradePlan(**pending["plan"])
                    position = open_position(
                        plan,
                        t,
                        pending["signal_time"],
                        float(row.open),
                        state["balance"],
                        self.cfg,
                        multiplier * pending["risk_multiplier"],
                        regime=pending["regime"],
                        volatility=pending["volatility"],
                        score=pending["score"],
                        quality=pending["quality"],
                    )
                state["pending"] = None
                if position is not None:
                    closed = advance_position(
                        position, row, t if gap else closed_at, self.cfg, force="data_gap" if gap else None
                    )
                    self._save_trade(conn, position, closed)
                    if closed:
                        state["balance"] += position.pnl
                        guard.record(position.pnl)
                        position = None
                equity = (
                    position.equity(state["balance"], float(row.close), self.cfg.risk.fee)
                    if position
                    else state["balance"]
                )
                multiplier, state["protection"] = guard.update(closed_at, equity)
                history = features.iloc[
                    max(
                        0, i - max(self.cfg.strategy.warmup_bars, self.cfg.indicators.structure_window) - 10
                    ) : i + 1
                ]
                a = analyze(history, self.cfg)
                self.db.record_signal(
                    a, self.exchange, self.symbol, self.timeframe, self.source, self.strategy_key, conn
                )
                signature = f"{a.direction}:{a.regime}:{row.structure}"
                if (
                    gate.permit(state["ordinal"], a.eligible, signature)
                    and position is None
                    and multiplier > 0
                    and allow_new_entries
                ):
                    state["pending"] = {
                        "plan": a.plan.to_dict(),
                        "signal_time": str(closed_at),
                        "risk_multiplier": a.risk_multiplier,
                        "regime": a.regime,
                        "volatility": a.volatility,
                        "score": a.score.overall,
                        "quality": a.quality,
                    }
                    gate.fired(state["ordinal"], signature)
                state["last_bar"], state["ordinal"], state["equity"] = str(t), state["ordinal"] + 1, equity
            state["position"] = position.to_dict() if position else None
            state["guard"], state["gate"] = asdict(guard), asdict(gate)
            conn.execute(
                "INSERT OR REPLACE INTO paper_accounts VALUES(?,?,?)", (self.account, dumps(state), str(now))
            )
        return state

    def set_enabled(self, enabled: bool) -> None:
        """Persist activation across restarts; disabling cancels pending entries, not exits."""
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT state FROM paper_accounts WHERE account=?", (self.account,)).fetchone()
            state = json.loads(row[0]) if row else self._initial()
            state["enabled"] = enabled
            if not enabled:
                state["pending"] = None
            conn.execute(
                "INSERT OR REPLACE INTO paper_accounts VALUES(?,?,?)",
                (self.account, dumps(state), str(pd.Timestamp.now(tz="UTC"))),
            )

    def reset_protection(self, now: object | None = None) -> None:
        """Clear latched protection without deleting trades or restoring starting capital."""
        t = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT state FROM paper_accounts WHERE account=?", (self.account,)).fetchone()
            if row:
                state = json.loads(row[0])
                guard = RiskGuard(self.cfg.risk)
                guard.reset(t, state.get("equity", state["balance"]))
                state["guard"] = asdict(guard)
                state["protection"] = "User reset"
                conn.execute(
                    "UPDATE paper_accounts SET state=?,updated_at=? WHERE account=?",
                    (dumps(state), str(t), self.account),
                )
