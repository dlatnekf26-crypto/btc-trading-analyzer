"""Binance spot OHLCV adapter through CCXT's public API."""

import ccxt
import math
import pandas as pd
from typing import Callable
from btc_analyzer.config import TIMEFRAMES
from btc_analyzer.candles import candle_close
from btc_analyzer.data.base_provider import BaseExchangeProvider, DataError, normalize, retry, utc


class BinanceProvider(BaseExchangeProvider):
    name = "Binance"
    default_symbol = "BTC/USDT"

    def __init__(self, client: object | None = None) -> None:
        # No keys are read; V1 is public spot data only.
        self.client = client or ccxt.binance(
            {
                "enableRateLimit": True,
                "timeout": 15000,
                # Respect the platform's HTTPS proxy and trusted CA bindings.
                # This preserves TLS verification and never installs a bypass route.
                "requests_trust_env": True,
                # Official Binance public market-data service. No trading/private
                # endpoint is redirected, and geographic refusals remain errors.
                "urls": {"api": {"public": "https://data-api.binance.vision/api/v3"}},
                "options": {"defaultType": "spot", "fetchMarkets": {"types": ["spot"]}},
            }
        )

    def _fetch_page(self, symbol: str, timeframe: str, cursor: int) -> list:
        return self._public_call(lambda: self.client.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000))

    def _public_call(self, call: Callable) -> object:
        """Normalize permanent failures before retrying genuinely transient errors."""
        try:
            return call()
        except ccxt.BaseError as exc:
            # CCXT may classify HTTP 451 as NetworkError and omit its status
            # from the message. Inspect the HTTP exception chain, not credentials
            # or connection settings; a geographic refusal cannot be fixed by retry.
            cause = exc
            while cause is not None:
                response = getattr(cause, "response", None)
                if response is not None and getattr(response, "status_code", None) == 451:
                    raise DataError(
                        "Binance HTTP 451: 현재 실행 지역에서 거래소 서비스가 제한됩니다. "
                        "이 서버에서는 실시간 Binance 데이터를 제공할 수 없습니다."
                    ) from exc
                cause = cause.__cause__ or cause.__context__
            if isinstance(exc, (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded)):
                raise
            raise DataError(f"Binance public OHLCV failed: {type(exc).__name__}: {exc}") from exc

    def quote(self, symbol: str) -> dict:
        """Public spot ticker for display only; closed-candle signals never use it."""
        ticker = retry(
            lambda: self._public_call(lambda: self.client.fetch_ticker(symbol)),
            (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded),
        )
        try:
            price = float(ticker["last"])
            change = None if ticker.get("percentage") is None else float(ticker["percentage"])
            if not math.isfinite(price) or price <= 0:
                raise ValueError("Invalid ticker price")
            if change is not None and not math.isfinite(change):
                raise ValueError("Invalid ticker change")
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError("Binance의 현재가 응답이 유효하지 않습니다.") from exc
        return {"price": price, "change_24h": change, "observed_at": pd.Timestamp.now(tz="UTC").isoformat()}

    def fetch(self, symbol: str, timeframe: str, start: object, end: object) -> pd.DataFrame:
        """Page forwards in batches of at most 1000 and guard against stalled responses."""
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        cursor, until = int(utc(start).timestamp() * 1000), int(utc(end).timestamp() * 1000)
        if cursor >= until:
            raise ValueError("Start must precede end")
        rows: list = []
        while cursor < until:
            batch = retry(
                lambda: self._fetch_page(symbol, timeframe, cursor),
                (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded),
            )
            if not batch:
                break
            if any(len(r) != 6 for r in batch):
                raise DataError("Malformed Binance OHLCV response")
            latest = max(int(r[0]) for r in batch)
            if latest < cursor:
                raise DataError("Binance pagination did not advance")
            rows.extend(r for r in batch if cursor <= int(r[0]) < until)
            cursor = int(
                candle_close(pd.Timestamp(latest, unit="ms", tz="UTC"), timeframe).timestamp() * 1000
            )
            if cursor >= until:
                break
        return normalize(rows, timeframe)
