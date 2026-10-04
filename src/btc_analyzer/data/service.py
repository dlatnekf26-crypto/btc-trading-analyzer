"""SQLite TTL cache and explicit, reproducible OFFLINE demonstration data."""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
import numpy as np
import pandas as pd
from btc_analyzer.config import TIMEFRAMES, MTF_MAP
from btc_analyzer.data.base_provider import normalize, utc
from btc_analyzer.data.binance_provider import BinanceProvider
from btc_analyzer.data.upbit_provider import UpbitProvider


class DataService:
    """Persist identical public-data requests; no credentials stored in cache."""

    def __init__(self, db_path: str | Path, ttl: int = 300) -> None:
        self.path, self.ttl = Path(db_path), ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS market_cache (key TEXT PRIMARY KEY, created REAL, payload TEXT)"
            )
            conn.execute("DELETE FROM market_cache WHERE created < ?", (time.time() - max(ttl, 300),))

    def fetch(
        self, exchange: str, symbol: str, timeframe: str, start: object, end: object, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Use only unexpired cache entries; empty/error requests are never cached."""
        if exchange not in ("Binance", "Upbit"):
            raise ValueError("Unsupported exchange")
        start, end = utc(start), utc(end)
        key = hashlib.sha256(f"{exchange}:{symbol}:{timeframe}:{start}:{end}".encode()).hexdigest()
        with sqlite3.connect(self.path) as conn:
            item = conn.execute("SELECT created,payload FROM market_cache WHERE key=?", (key,)).fetchone()
        if not refresh and item and time.time() - item[0] < self.ttl:
            data = json.loads(item[1])
            result = normalize(data["rows"], timeframe)
            result.attrs["quality"] = data["quality"]
            result.attrs["cached"] = True
            return result
        provider = BinanceProvider() if exchange == "Binance" else UpbitProvider()
        result = provider.fetch(symbol, timeframe, start, end)
        if not result.empty:
            rows = [[int(t.timestamp() * 1000), *r] for t, r in zip(result.index, result.to_numpy().tolist())]
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO market_cache VALUES(?,?,?)",
                    (key, time.time(), json.dumps({"rows": rows, "quality": result.attrs["quality"]})),
                )
        return result

    def bundle(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: object,
        end: object,
        warmup: int = 240,
        refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """Each timeframe gets its own warmup; avoid downloading a year of minute bars."""
        return {
            tf: self.fetch(
                exchange,
                symbol,
                tf,
                utc(start) - pd.Timedelta(seconds=TIMEFRAMES[tf] * warmup),
                end,
                refresh=refresh,
            )
            for tf in MTF_MAP[timeframe]
        }


def demo_bundle(
    timeframe: str = "1h",
    bars: int = 800,
    seed: int = 42,
    end: object = "2026-01-01T00:00:00Z",
    price: float = 90_000,
) -> dict[str, pd.DataFrame]:
    """Synthetic, NOT live prices. All timeframes resample the SAME seeded price path.

    Higher-timeframe warmup requires 250 daily bars. Only the selected lower
    history window is exposed. Time is fixed by default for reproducible tests.
    """
    base_seconds = min(TIMEFRAMES[t] for t in MTF_MAP[timeframe])
    total = max(260 * 86400 // base_seconds, (bars + 250) * TIMEFRAMES[timeframe] // base_seconds)
    index = pd.date_range(end=utc(end), periods=total + 1, freq=pd.Timedelta(seconds=base_seconds))[:-1]
    rng = np.random.default_rng(seed)
    x = np.arange(total)
    # Alternating regimes and pullbacks; no selected future outcome influences signals.
    returns = 0.00005 * np.sin(x / 130) + rng.normal(0, 0.0013 * np.sqrt(base_seconds / 3600), total)
    closes = price * np.exp(np.cumsum(returns))
    opens = np.r_[closes[0], closes[:-1]]
    span = rng.uniform(0.0002, 0.002, total) * closes
    raw = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) + span,
            "low": np.minimum(opens, closes) - span,
            "close": closes,
            "volume": rng.lognormal(3, 0.6, total),
        },
        index=index,
    )
    raw.index.name = "timestamp"
    result = {}
    start = utc(end) - pd.Timedelta(seconds=TIMEFRAMES[timeframe] * bars)
    for tf in MTF_MAP[timeframe]:
        freq = pd.Timedelta(seconds=TIMEFRAMES[tf])
        df = (
            raw.resample(freq, origin="epoch")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )
        df = df.loc[
            (df.index + freq <= utc(end)) & (df.index >= start - pd.Timedelta(seconds=TIMEFRAMES[tf] * 240))
        ]
        df.attrs.update(
            {
                "timeframe": tf,
                "synthetic": True,
                "quality": {"missing_candles": 0, "invalid_rows": 0, "duplicates": 0},
            }
        )
        result[tf] = df
    return result
