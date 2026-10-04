"""Versioned SQLite schema, parameterized queries and transactional paper state."""

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sqlite3
from typing import Iterator
import numpy as np
import pandas as pd


def json_default(value: object) -> object:
    """Audit serialization for dataclasses, timestamps and NumPy scalars."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def dumps(value: object) -> str:
    return json.dumps(value, default=json_default, ensure_ascii=False, allow_nan=False)


class Database:
    """Local research database. WAL and BEGIN IMMEDIATE prevent double paper execution."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database was created by a newer application")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, data_source TEXT NOT NULL,
                    strategy_key TEXT NOT NULL, direction TEXT NOT NULL, score REAL, quality REAL,
                    regime TEXT, eligible INTEGER, payload TEXT NOT NULL,
                    UNIQUE(timestamp,exchange,symbol,timeframe,data_source,strategy_key,direction));
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    account TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY, account TEXT NOT NULL, timestamp TEXT NOT NULL,
                    exchange TEXT, symbol TEXT, timeframe TEXT, data_source TEXT, direction TEXT,
                    entry REAL, stop REAL, tp TEXT, position_size REAL, result TEXT, pnl REAL,
                    r_multiple REAL, signal_score REAL, regime TEXT, payload TEXT NOT NULL,
                    UNIQUE(account,timestamp));
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, exchange TEXT, symbol TEXT,
                    timeframe TEXT, data_source TEXT, settings TEXT, metrics TEXT, equity TEXT,
                    warnings TEXT);
                CREATE TABLE IF NOT EXISTS backtest_trades (
                    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES backtest_runs(id),
                    entry_time TEXT, exit_time TEXT, pnl REAL, payload TEXT);
                CREATE TABLE IF NOT EXISTS strategy_settings (
                    name TEXT PRIMARY KEY, updated_at TEXT NOT NULL, settings TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_signal_market ON signals(exchange,symbol,timeframe,timestamp);
                CREATE INDEX IF NOT EXISTS ix_trade_account ON paper_trades(account);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on failure; no shared cross-thread connection."""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_signal(
        self,
        analysis: object,
        exchange: str,
        symbol: str,
        timeframe: str,
        source: str,
        strategy_key: str,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Idempotent snapshots; all source/settings dimensions prevent demo/live collisions."""
        a = analysis
        args = (
            a.timestamp,
            exchange,
            symbol,
            timeframe,
            source,
            strategy_key,
            a.direction,
            a.score.overall,
            a.quality,
            a.regime,
            int(a.eligible),
            dumps(a),
        )
        sql = "INSERT OR IGNORE INTO signals(timestamp,exchange,symbol,timeframe,data_source,strategy_key,direction,score,quality,regime,eligible,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
        if conn is not None:
            conn.execute(sql, args)
        else:
            with self.connect(write=True) as connection:
                connection.execute(sql, args)

    def save_settings(self, name: str, settings: dict) -> None:
        """Store non-secret configuration only."""
        with self.connect(write=True) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO strategy_settings VALUES(?,?,?)",
                (name, pd.Timestamp.now(tz="UTC").isoformat(), dumps(settings)),
            )

    def load_settings(self, name: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT settings FROM strategy_settings WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_backtest(self, result: object, exchange: str, symbol: str, timeframe: str, source: str) -> int:
        """Persist a complete run and its trades atomically."""
        r = result
        equity = [
            {"timestamp": str(t), "equity": float(row.equity), "buy_hold": float(row.buy_hold)}
            for t, row in r.equity.iterrows()
        ]
        with self.connect(write=True) as conn:
            cur = conn.execute(
                "INSERT INTO backtest_runs(created_at,exchange,symbol,timeframe,data_source,settings,metrics,equity,warnings) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    pd.Timestamp.now(tz="UTC").isoformat(),
                    exchange,
                    symbol,
                    timeframe,
                    source,
                    dumps(r.settings),
                    dumps(r.metrics),
                    dumps(equity),
                    dumps(r.warnings),
                ),
            )
            run_id = cur.lastrowid
            for trade in r.trades.to_dict("records"):
                conn.execute(
                    "INSERT INTO backtest_trades(run_id,entry_time,exit_time,pnl,payload) VALUES(?,?,?,?,?)",
                    (run_id, trade["entry_time"], trade["exit_time"], trade["pnl"], dumps(trade)),
                )
        return int(run_id)

    def history(self, table: str, limit: int = 500, account: str | None = None) -> pd.DataFrame:
        """Read known tables only; never interpolate user-controlled identifiers."""
        if table not in {"signals", "paper_trades", "backtest_runs", "strategy_settings"}:
            raise ValueError("Unknown history table")
        if not 1 <= limit <= 10000:
            raise ValueError("Invalid history limit")
        with self.connect() as conn:
            if account and table == "paper_trades":
                return pd.read_sql_query(
                    "SELECT * FROM paper_trades WHERE account=? ORDER BY id DESC LIMIT ?",
                    conn,
                    params=(account, limit),
                )
            order = "updated_at" if table == "strategy_settings" else "id"
            return pd.read_sql_query(
                f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", conn, params=(limit,)
            )
