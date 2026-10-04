"""Read-only exchange smoke test; exits nonzero for any requested failed provider."""

import argparse
import logging
import pandas as pd
from btc_analyzer.data.binance_provider import BinanceProvider
from btc_analyzer.data.upbit_provider import UpbitProvider


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange", choices=["Binance", "Upbit", "both"], default="both")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    end = pd.Timestamp.now(tz="UTC").floor("1h")
    failed = []
    for provider in (BinanceProvider(), UpbitProvider()):
        if args.exchange not in ("both", provider.name):
            continue
        try:
            data = provider.fetch(provider.default_symbol, "1h", end - pd.Timedelta(hours=6), end)
            assert len(data) >= 3, "Too few closed candles"
            assert (data.high >= data.close).all()
            assert data.index.is_monotonic_increasing and str(data.index.tz) == "UTC"
            print(
                f"{provider.name}: PASS {len(data)} closed OHLCV candles; latest close={data.close.iloc[-1]:,.2f}"
            )
        except Exception as exc:
            failed.append(provider.name)
            print(f"{provider.name}: FAIL {type(exc).__name__}: {exc}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
