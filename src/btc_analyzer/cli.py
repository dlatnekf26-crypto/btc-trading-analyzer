"""Reproducible headless analysis/backtest/robustness and optional paper polling."""

import argparse
import logging
import os
from pathlib import Path
import time
import pandas as pd
from dotenv import load_dotenv
from btc_analyzer.config import AppConfig, TIMEFRAMES
from btc_analyzer.analysis.multi_timeframe import prepare
from btc_analyzer.backtest.engine import BacktestEngine
from btc_analyzer.backtest.robustness import run_robustness
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.paper.paper_trading import PaperTrader
from btc_analyzer.storage.database import Database, dumps
from btc_analyzer.strategy.signal_engine import analyze

log = logging.getLogger(__name__)


def main() -> None:
    """Run locally without Streamlit or private API credentials."""
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["demo", "live"], default="demo")
    parser.add_argument("--exchange", choices=["Binance", "Upbit"], default="Binance")
    parser.add_argument("--symbol")
    parser.add_argument("--timeframe", choices=list(TIMEFRAMES), default="1h")
    parser.add_argument("--start", help="UTC inclusive evaluation start (live only)")
    parser.add_argument("--end", help="UTC exclusive end (live only)")
    parser.add_argument("--bars", type=int, default=800, help="Demo evaluation candles")
    parser.add_argument("--config", type=Path, help="Non-secret JSON settings")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("BTC_DB_PATH", "data/analyzer.sqlite3")))
    parser.add_argument("--output", type=Path, default=Path("data/reports"))
    parser.add_argument("--robustness", action="store_true")
    parser.add_argument("--compact", action="store_true", help="ATR-only 3-point sensitivity")
    parser.add_argument("--paper-tick", action="store_true")
    parser.add_argument(
        "--paper-watch", action="store_true", help="Poll public candles for virtual orders only"
    )
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.bars < 30 or args.interval < 10:
        parser.error("Use at least 30 demo bars and a polling interval >=10 seconds")
    if args.paper_watch and args.source != "live":
        parser.error("Paper watch requires live public candles; static demo cannot advance time")
    logging.basicConfig(level=os.getenv("BTC_LOG_LEVEL", "INFO"))
    cfg = AppConfig.load(args.config) if args.config else AppConfig()
    db = Database(args.db)
    symbol = args.symbol or ("BTC/USDT" if args.exchange == "Binance" else "KRW-BTC")

    def fetch() -> tuple[dict, pd.Timestamp]:
        if args.source == "demo":
            bundle = demo_bundle(
                args.timeframe, args.bars, price=90_000 if args.exchange == "Binance" else 130_000_000
            )
            return bundle, bundle[args.timeframe].index[-min(args.bars, len(bundle[args.timeframe]))]
        end = pd.Timestamp.now(tz="UTC") if args.paper_watch else args.end or pd.Timestamp.now(tz="UTC")
        start = args.start or pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
        return DataService(args.db, ttl=45).bundle(args.exchange, symbol, args.timeframe, start, end), start

    if args.paper_watch:
        trader = PaperTrader(db, cfg, args.exchange, symbol, args.timeframe, "live")
        trader.set_enabled(True)
        log.info("VIRTUAL paper polling account=%s (Ctrl+C to stop)", trader.account)
        try:
            while True:
                try:
                    bundle, _ = fetch()
                    features = prepare(bundle, args.timeframe, cfg)
                    enabled = trader.state().get("enabled", False)
                    state = trader.tick(features, allow_new_entries=enabled)
                    log.info(
                        "Virtual equity %.2f; protection %s",
                        state.get("equity", state["balance"]),
                        state["protection"],
                    )
                except (ValueError, RuntimeError, OSError) as exc:
                    log.error("Paper update failed: %s", exc)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log.info("Polling stopped. Positions/state retained; resume polling for protective exits.")
        return
    bundle, start = fetch()
    features = prepare(bundle, args.timeframe, cfg)
    a = analyze(features, cfg)
    trader = PaperTrader(db, cfg, args.exchange, symbol, args.timeframe, args.source)
    db.record_signal(a, args.exchange, symbol, args.timeframe, args.source, trader.strategy_key)
    r = BacktestEngine(cfg).run(bundle, args.timeframe, start=start, features=features)
    run_id = db.save_backtest(r, args.exchange, symbol, args.timeframe, args.source)
    args.output.mkdir(parents=True, exist_ok=True)
    r.equity.to_csv(args.output / f"run-{run_id}-equity.csv")
    r.trades.to_csv(args.output / f"run-{run_id}-trades.csv", index=False)
    summary = {
        "source": args.source,
        "exchange": args.exchange,
        "symbol": symbol,
        "timeframe": args.timeframe,
        "run_id": run_id,
        "analysis": a.to_dict(),
        "metrics": r.metrics,
        "warnings": r.warnings,
    }
    if args.robustness:
        report = run_robustness(bundle, args.timeframe, cfg, start, compact=args.compact)
        summary["robustness"] = report["assessment"]
        summary["splits"] = {key: value.metrics for key, value in report["splits"].items()}
        summary["simulation"] = {
            k: v for k, v in report["simulation"].items() if k not in ("equity_bands", "drawdowns")
        }
        for key in ("parameters", "costs", "walk_forward"):
            report[key].to_csv(args.output / f"run-{run_id}-{key}.csv", index=False)
    if args.paper_tick:
        summary["paper"] = trader.tick(features)
    text = dumps(summary)
    (args.output / f"run-{run_id}-summary.json").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
