"""Transactional durability, deduplication, source isolation and virtual fills."""

from dataclasses import replace
import json
import pandas as pd
import pytest
from btc_analyzer.config import AppConfig
from btc_analyzer.paper.paper_trading import PaperTrader
from btc_analyzer.storage.database import Database, dumps
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.backtest.engine import BacktestEngine
from btc_analyzer.strategy.entry_engine import TradePlan


def test_signal_logging_idempotent(tmp_path, features):
    db = Database(tmp_path / "test.sqlite")
    a = analyze(features)
    for _ in range(2):
        db.record_signal(a, "Binance", "BTC/USDT", "1h", "demo", "cfg")
    assert len(db.history("signals")) == 1
    db.record_signal(a, "Binance", "BTC/USDT", "1h", "live", "cfg")
    assert len(db.history("signals")) == 2
    db.save_settings("default", AppConfig().to_dict())
    assert db.load_settings("default")["risk"]["capital"] == 10000
    with pytest.raises(ValueError):
        db.history("paper_accounts; DROP TABLE signals")


def test_paper_baseline_restart_and_unclosed_bar(tmp_path, features):
    db = Database(tmp_path / "paper.sqlite")
    cfg = AppConfig()
    trader = PaperTrader(db, cfg, "Binance", "BTC/USDT", "1h", "demo")
    first = trader.tick(features.iloc[:-1], now=features.index[-1])
    assert first["ordinal"] == 1
    assert first["last_bar"] == str(features.index[-2])
    same = trader.tick(features, now=features.index[-1] + pd.Timedelta(minutes=30))
    assert same["ordinal"] == 1
    restarted = PaperTrader(Database(db.path), cfg, "Binance", "BTC/USDT", "1h", "demo")
    updated = restarted.tick(features, now=features.index[-1] + pd.Timedelta(hours=1))
    assert updated["ordinal"] == 2
    assert restarted.tick(features)["ordinal"] == 2
    assert len(db.history("signals")) == 2


def test_monthly_paper_ignores_february_until_actual_march_close(tmp_path, features):
    frame = features.tail(3).copy()
    frame.index = pd.date_range("2024-01-01", periods=3, freq="MS", tz="UTC", name="timestamp")
    trader = PaperTrader(
        Database(tmp_path / "monthly-paper.sqlite"), AppConfig(), "Binance", "BTC/USDT", "1M", "demo"
    )
    first = trader.tick(frame, now="2024-02-01T00:00Z")
    assert first["last_bar"] == str(frame.index[0])
    still_january = trader.tick(frame, now="2024-02-29T23:59Z")
    assert still_january["ordinal"] == 1
    february = trader.tick(frame, now="2024-03-01T00:00Z")
    assert february["ordinal"] == 2
    assert february["last_bar"] == str(frame.index[1])


def test_paper_fills_pending_next_open(tmp_path, features):
    db = Database(tmp_path / "paper.sqlite")
    cfg = AppConfig()
    trader = PaperTrader(db, cfg, "Binance", "BTC/USDT", "1h", "demo")
    df = features.tail(3).copy()
    df[["open", "close"]] = 100.0
    df.high = 101.0
    df.low = 99.0
    state = trader.tick(df.iloc[:1], now=df.index[1])
    plan = TradePlan("long", 95, 105, 100, 90, (120, 130, 140), (2, 3, 4))
    state["pending"] = {
        "plan": plan.to_dict(),
        "signal_time": str(df.index[1]),
        "risk_multiplier": 1,
        "regime": "Uptrend",
        "volatility": "Normal Volatility",
        "score": 80,
        "quality": 90,
    }
    with db.connect(write=True) as conn:
        conn.execute("UPDATE paper_accounts SET state=? WHERE account=?", (dumps(state), trader.account))
    df.iloc[1, df.columns.get_loc("high")] = 145
    updated = trader.tick(df.iloc[:2], now=df.index[2])
    history = db.history("paper_trades", account=trader.account)
    assert len(history) == 1
    assert history.iloc[0].result == "win"
    assert history.iloc[0].entry == pytest.approx(100.05)
    assert updated["balance"] == pytest.approx(10000 + history.iloc[0].pnl)
    trader.tick(df.iloc[:2], now=df.index[2])
    assert len(db.history("paper_trades", account=trader.account)) == 1


def test_paper_activation_survives_restart(tmp_path, features):
    db = Database(tmp_path / "paper.sqlite")
    trader = PaperTrader(db, AppConfig(), "Binance", "BTC/USDT", "1h", "demo")
    trader.set_enabled(True)
    assert trader.state()["enabled"]
    restored = PaperTrader(Database(db.path), AppConfig(), "Binance", "BTC/USDT", "1h", "demo")
    assert restored.state()["enabled"]
    restored.set_enabled(False)
    assert not restored.state()["enabled"]
    assert restored.state()["pending"] is None
    other = PaperTrader(db, AppConfig(), "Binance", "BTC/USDT", "1h", "live")
    assert other.account != trader.account


def test_storage_rollback(tmp_path):
    db = Database(tmp_path / "rollback.sqlite")
    with pytest.raises(RuntimeError):
        with db.connect(write=True) as conn:
            conn.execute("INSERT INTO strategy_settings VALUES(?,?,?)", ("x", "t", "{}"))
            raise RuntimeError("fail")
    assert db.load_settings("x") is None


def test_backtest_save(tmp_path, features):
    db = Database(tmp_path / "backtest.sqlite")
    base = analyze(features)
    plan = TradePlan("long", 95, 105, 100, 90, (120, 130, 140), (2, 3, 4))
    frame = features.tail(4).copy()
    frame[["open", "close"]] = 100.0
    frame.high = 101.0
    frame.low = 99.0
    frame.iloc[1, frame.columns.get_loc("high")] = 145

    def signal(h, c):
        return replace(base, eligible=h.index[-1] == frame.index[0], plan=plan, risk_multiplier=1)

    result = BacktestEngine().run({}, "1h", start=frame.index[0], features=frame, signal_fn=signal)
    run_id = db.save_backtest(result, "Binance", "BTC/USDT", "1h", "demo")
    with db.connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM backtest_trades WHERE run_id=?", (run_id,)).fetchone()[0] == 1
        )
    assert json.loads(db.history("backtest_runs").iloc[0].metrics)["number_of_trades"] == 1
