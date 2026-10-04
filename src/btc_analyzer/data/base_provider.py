"""UTC candle contract, validation, retry and public-only exchange interface."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
import logging
import time
from typing import TypeVar
import numpy as np
import pandas as pd
from btc_analyzer.config import TIMEFRAMES
from btc_analyzer.candles import candle_close, candle_grid, missing_intervals

log = logging.getLogger(__name__)
COLUMNS = ["open", "high", "low", "close", "volume"]
T = TypeVar("T")


class DataError(RuntimeError):
    """A public market-data request failed or returned unusable data."""


def utc(value: object) -> pd.Timestamp:
    """Interpret naive user dates as UTC; convert timezone-aware dates to UTC."""
    t = pd.Timestamp(value)
    if pd.isna(t):
        raise ValueError("Invalid timestamp")
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def retry(
    operation: Callable[[], T],
    errors: tuple[type[Exception], ...],
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Bounded exponential retry without changing TLS verification."""
    for i in range(attempts):
        try:
            return operation()
        except errors as exc:
            if i == attempts - 1:
                raise DataError(
                    f"Market data failed after {attempts} attempts: {type(exc).__name__}: {exc}"
                ) from exc
            log.warning("Transient public data failure %s; retry %d", type(exc).__name__, i + 1)
            sleep(min(2**i, 8))
    raise DataError("No request attempted")


def normalize(
    rows: Iterable, timeframe: str, *, now: object | None = None, timestamp_unit: str | None = "ms"
) -> pd.DataFrame:
    """Return validated CLOSED candles indexed by their UTC OPEN timestamp.

    Gaps are reported, never silently filled. Invalid/off-grid bars are removed;
    downstream indicators restart warmup after each gap. Duplicate counts are
    retained in attrs. Volume zero is valid (Upbit may omit empty intervals).
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported timeframe")
    df = pd.DataFrame(list(rows), columns=["timestamp", *COLUMNS])
    raw_count = len(df)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit=timestamp_unit, utc=True, errors="coerce")
    for name in COLUMNS:
        df[name] = pd.to_numeric(df[name], errors="coerce")
    current = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    valid = df["timestamp"].notna() & np.isfinite(df[COLUMNS]).all(axis=1)
    valid &= (df[["open", "high", "low", "close"]] > 0).all(axis=1) & (df.volume >= 0)
    valid &= df.high >= df[["open", "close", "low"]].max(axis=1)
    valid &= df.low <= df[["open", "close", "high"]].min(axis=1)
    on_grid = candle_grid(df.timestamp, timeframe)
    invalid_count = int((~(valid & on_grid)).sum())
    df = df.loc[valid & on_grid]
    closed_at = candle_close(df.timestamp, timeframe)
    unfinished_count = int((closed_at > current).sum())
    df = df.loc[closed_at <= current]
    duplicates = int(df.timestamp.duplicated().sum())
    df = df.drop_duplicates("timestamp", keep="last").sort_values("timestamp").set_index("timestamp")
    gaps = missing_intervals(df.index, timeframe)
    df.attrs["quality"] = {
        "raw_rows": raw_count,
        "invalid_rows": invalid_count,
        "duplicates": duplicates,
        "unfinished_rows": unfinished_count,
        "missing_candles": int(gaps.sum()),
        "gap_events": int((gaps > 0).sum()),
    }
    df.attrs["timeframe"] = timeframe
    return df.astype(float)


class BaseExchangeProvider(ABC):
    """Public OHLCV only; deliberately contains no order or private API methods."""

    name: str
    default_symbol: str

    @abstractmethod
    def fetch(self, symbol: str, timeframe: str, start: object, end: object) -> pd.DataFrame:
        """Fetch closed candles with opening timestamps in [start, end)."""
