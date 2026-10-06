"""SQLite TTL cache and explicit, reproducible OFFLINE demonstration data."""

from functools import lru_cache
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import numpy as np
import pandas as pd
from btc_analyzer.config import TIMEFRAMES, MTF_MAP, COMPOSITE_TIMEFRAMES
from btc_analyzer.candles import candle_boundary, candle_close, history_start, resample_candles
from btc_analyzer.data.base_provider import DataError, normalize, utc
from btc_analyzer.data.binance_provider import BinanceProvider
from btc_analyzer.data.upbit_provider import UpbitProvider


class DataService:
    """Persist identical public-data requests; no credentials stored in cache."""

    def __init__(self, db_path: str | Path, ttl: int = 300) -> None:
        self.path, self.ttl = Path(db_path), ttl
        self._providers = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS market_cache (key TEXT PRIMARY KEY, created REAL, payload TEXT)"
            )
            conn.execute(
                "DELETE FROM market_cache WHERE (key NOT LIKE 'history:%' AND created < ?) "
                "OR (key LIKE 'history:%' AND created < ?)",
                (time.time() - max(ttl, 86400), time.time() - max(ttl, 7 * 86400)),
            )

    def fetch(
        self, exchange: str, symbol: str, timeframe: str, start: object, end: object, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Use only unexpired cache entries; empty/error requests are never cached."""
        if exchange not in ("Binance", "Upbit"):
            raise ValueError("Unsupported exchange")
        start, end = utc(start), utc(end)
        # The same closed weekly/monthly history does not change every minute.
        # A new closing boundary changes the key immediately, regardless of TTL.
        end = candle_boundary(end, timeframe)
        if start >= end:
            return normalize([], timeframe)
        key = hashlib.sha256(f"{exchange}:{symbol}:{timeframe}:{start}:{end}".encode()).hexdigest()
        with sqlite3.connect(self.path) as conn:
            item = conn.execute("SELECT created,payload FROM market_cache WHERE key=?", (key,)).fetchone()
        cache_ttl = max(self.ttl, min(TIMEFRAMES[timeframe], 86400))
        if not refresh and item and time.time() - item[0] < cache_ttl:
            data = json.loads(item[1])
            result = normalize(data["rows"], timeframe)
            result.attrs["quality"] = data["quality"]
            result.attrs["cached"] = True
            return result
        if exchange not in self._providers:
            self._providers[exchange] = BinanceProvider() if exchange == "Binance" else UpbitProvider()
        provider = self._providers[exchange]
        result = provider.fetch(symbol, timeframe, start, end)
        if not result.empty and candle_close(result.index[-1], timeframe) == end:
            rows = [[int(t.timestamp() * 1000), *r] for t, r in zip(result.index, result.to_numpy().tolist())]
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO market_cache VALUES(?,?,?)",
                    (key, time.time(), json.dumps({"rows": rows, "quality": result.attrs["quality"]})),
                )
        return result

    def history(self, exchange, symbol, timeframe, end, bars, *, refresh=False):
        """Reuse closed history across boundaries; fetch just the revised/new tail.

        Forced refresh and expired same-boundary data perform a full request.
        Missing latest candles or provider failures never pass as fresh history.
        """
        if exchange not in ("Binance", "Upbit") or timeframe not in COMPOSITE_TIMEFRAMES:
            raise ValueError("Unsupported historical market")
        if not isinstance(bars, int) or not 1 <= bars <= 3000:
            raise ValueError("History must contain 1–3000 candles")
        end = candle_boundary(utc(end), timeframe)
        start = history_start(end, timeframe, bars)
        if exchange == "Binance":
            start = max(start, utc("2017-08-01"))
        key = "history:" + hashlib.sha256(f"{exchange}:{symbol}:{timeframe}:{bars}".encode()).hexdigest()
        with sqlite3.connect(self.path) as conn:
            item = conn.execute("SELECT created,payload FROM market_cache WHERE key=?", (key,)).fetchone()
        previous = None
        if item and not refresh:
            payload = json.loads(item[1])
            previous_end = utc(payload["end"])
            previous = normalize(payload["rows"], timeframe, now=previous_end)
            previous.attrs["quality"] = payload["quality"]
            lifetime = max(self.ttl, min(TIMEFRAMES[timeframe], 86400))
            if end == previous_end and time.time() - item[0] < lifetime:
                previous.attrs["cached"] = True
                return previous
            if end > previous_end and not previous.empty and previous_end > start:
                # Include one overlap candle so revisions replace its old value.
                tail = self.fetch(exchange, symbol, timeframe, previous.index[-1], end)
                joined = pd.concat([previous, tail])
                joined = joined.loc[~joined.index.duplicated(keep="last")]
                joined = joined.loc[(joined.index >= start) & (candle_close(joined.index, timeframe) <= end)]
                rows = [
                    [int(t.timestamp() * 1000), *r] for t, r in zip(joined.index, joined.to_numpy().tolist())
                ]
                result = normalize(rows, timeframe, now=end)
                result.attrs["quality"]["invalid_rows"] += tail.attrs.get("quality", {}).get(
                    "invalid_rows", 0
                )
            else:
                previous = None
        if previous is None or refresh:
            result = self.fetch(exchange, symbol, timeframe, start, end, refresh=refresh)
        if not result.empty and candle_close(result.index[-1], timeframe) == end:
            rows = [[int(t.timestamp() * 1000), *r] for t, r in zip(result.index, result.to_numpy().tolist())]
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO market_cache VALUES(?,?,?)",
                    (
                        key,
                        time.time(),
                        json.dumps(
                            {"rows": rows, "quality": result.attrs["quality"], "end": end.isoformat()}
                        ),
                    ),
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
        include_macro: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """Each timeframe gets its own warmup; avoid downloading a year of minute bars."""
        result = {
            tf: self.fetch(
                exchange,
                symbol,
                tf,
                history_start(utc(start), tf, warmup),
                end,
                refresh=refresh,
            )
            for tf in MTF_MAP[timeframe]
        }
        if include_macro:
            for tf in COMPOSITE_TIMEFRAMES:
                if tf in result:
                    continue
                # A latest snapshot needs a bounded window, not years of hourly
                # candles just because a monthly chart is being viewed.
                # Hour-of-day observations need 30 days. Still one Binance
                # page (720 < 1000), reusing this same bundle/cache request.
                bars = max(warmup, 720 if tf == "1h" else 260)
                since = history_start(candle_boundary(utc(end), tf), tf, bars)
                if exchange == "Binance":
                    since = max(since, utc("2017-08-01"))
                try:
                    result[tf] = self.fetch(exchange, symbol, tf, since, end, refresh=refresh)
                except DataError as exc:
                    # An absent macro frame is explicit and disables composite
                    # recommendations; the successfully fetched chart stays usable.
                    result[tf] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                    result[tf].attrs["error"] = str(exc)
        return result


def demo_bundle(
    timeframe: str = "1h",
    bars: int = 800,
    seed: int = 42,
    end: object = "2026-01-01T00:00:00Z",
    price: float = 90_000,
    include_macro: bool = False,
    history_limits: dict[str, int] | None = None,
    only_timeframe: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Synthetic, NOT live prices. All timeframes resample the SAME seeded price path.

    Higher-timeframe warmup requires 250 daily bars. Only the selected lower
    history window is exposed. Time is fixed by default for reproducible tests.
    """
    requested = tuple(dict.fromkeys((*MTF_MAP[timeframe], *(COMPOSITE_TIMEFRAMES if include_macro else ()))))
    base_seconds = min(TIMEFRAMES[t] for t in MTF_MAP[timeframe])
    total = max(260 * 86400 // base_seconds, (bars + 250) * TIMEFRAMES[timeframe] // base_seconds)
    if include_macro or timeframe in ("1w", "1M"):
        # Same path for all macro views; mirror Binance's actual history length.
        base_seconds = min(base_seconds, 900)
        total = max(1, int((utc(end) - utc("2017-09-01")).total_seconds() // base_seconds))
    if history_limits and any(
        tf not in requested or not isinstance(count, int) or not 1 <= count <= 3000
        for tf, count in history_limits.items()
    ):
        raise ValueError("Demo history must use requested frames and 1–3000 bars.")
    if only_timeframe is not None:
        if only_timeframe not in requested:
            raise ValueError("Demo timeframe is unavailable.")
        requested = (only_timeframe,)
    raw = _demo_path(base_seconds, total, seed, utc(end).isoformat(), price)
    result = {}
    start = history_start(utc(end), timeframe, bars)
    for tf in requested:
        df = resample_candles(raw, tf)
        since = history_start(start, tf, 240)
        if tf not in MTF_MAP[timeframe]:
            since = history_start(utc(end), tf, 260)
        if history_limits and tf in history_limits:
            since = history_start(candle_boundary(utc(end), tf), tf, history_limits[tf])
        df = df.loc[(candle_close(df.index, tf) <= utc(end)) & (df.index >= since)]
        df.attrs.update(
            {
                "timeframe": tf,
                "synthetic": True,
                "quality": {"missing_candles": 0, "invalid_rows": 0, "duplicates": 0},
            }
        )
        result[tf] = df
    return result


@lru_cache(maxsize=1)
def _demo_path(base_seconds, total, seed, end, price):
    """One bounded, read-only internal price path shared by demonstration views."""
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
    return raw
