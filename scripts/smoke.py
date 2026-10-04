"""Offline end-to-end readiness: causal analysis, backtest, SQLite and paper restart."""

import tempfile
from pathlib import Path
from btc_analyzer.data.service import demo_bundle
from btc_analyzer.analysis.multi_timeframe import prepare
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.backtest.engine import BacktestEngine
from btc_analyzer.storage.database import Database
from btc_analyzer.paper.paper_trading import PaperTrader
from btc_analyzer.config import AppConfig


def main() -> None:
    cfg = AppConfig()
    bundle = demo_bundle("1h", bars=400)
    features = prepare(bundle, "1h", cfg)
    a = analyze(features, cfg)
    assert 0 <= a.score.overall <= 100 and a.plan is not None
    r = BacktestEngine(cfg).run(bundle, "1h", start=features.index[-400])
    assert len(r.equity) == 401 and r.metrics["final_capital"] > 0
    with tempfile.TemporaryDirectory() as folder:
        db = Database(Path(folder) / "smoke.sqlite")
        run_id = db.save_backtest(r, "Binance", "BTC/USDT", "1h", "demo")
        assert run_id == 1 and len(db.history("backtest_runs")) == 1
        trader = PaperTrader(db, cfg, "Binance", "BTC/USDT", "1h", "demo")
        state = trader.tick(features.iloc[:-1], now=features.index[-1])
        assert state["ordinal"] == 1
        resumed = PaperTrader(Database(db.path), cfg, "Binance", "BTC/USDT", "1h", "demo")
        assert resumed.tick(features)["ordinal"] == 2
    print(
        f"PASS: {len(bundle)} timeframes; causal indicators/scoring; {len(r.equity)} equity observations; SQLite; paper restart"
    )
    print(
        f"Completed strategy trades: {len(r.trades)} (zero trades is disclosed, not profitability evidence)"
    )


if __name__ == "__main__":
    main()
