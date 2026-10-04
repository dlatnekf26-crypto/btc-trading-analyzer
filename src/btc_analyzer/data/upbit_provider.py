"""Upbit public REST adapter. Native 240-minute candles support 4h."""

import time
import requests
import pandas as pd
from btc_analyzer.config import TIMEFRAMES
from btc_analyzer.data.base_provider import BaseExchangeProvider, DataError, normalize, retry, utc


class UpbitProvider(BaseExchangeProvider):
    name = "Upbit"
    default_symbol = "KRW-BTC"

    def __init__(self, session: requests.Session | None = None, delay: float = 0.13) -> None:
        self.session = session or requests.Session()
        self.delay = delay  # < 10 requests/second, stricter remaining-request header applied below.

    def _request(self, endpoint: str, params: dict) -> list:
        response = self.session.get(endpoint, params=params, timeout=15)
        if response.status_code in (418, 429) or response.status_code >= 500:
            wait = min(float(response.headers.get("Retry-After", "1")), 30)
            time.sleep(max(0, wait))
            raise requests.HTTPError(f"Upbit temporary status {response.status_code}")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise DataError("Upbit response is not a candle list")
        remaining = response.headers.get("Remaining-Req", "")
        if "sec=0" in remaining:
            time.sleep(1)
        return payload

    def fetch(self, symbol: str, timeframe: str, start: object, end: object) -> pd.DataFrame:
        """Page backwards using exclusive UTC 'to'; never substitute local KST timestamps."""
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        since, until = utc(start), utc(end)
        if since >= until:
            raise ValueError("Start must precede end")
        endpoint = "https://api.upbit.com/v1/candles/" + (
            "days" if timeframe == "1d" else f"minutes/{TIMEFRAMES[timeframe] // 60}"
        )
        cursor = until
        rows = []
        while cursor > since:
            params = {"market": symbol, "count": 200, "to": cursor.strftime("%Y-%m-%dT%H:%M:%SZ")}
            batch = retry(lambda: self._request(endpoint, params), (requests.RequestException, ValueError))
            if not batch:
                break
            try:
                times = [utc(r["candle_date_time_utc"]) for r in batch]
                oldest = min(times)
                if oldest >= cursor:
                    raise DataError("Upbit pagination did not advance")
                for t, r in zip(times, batch):
                    if since <= t < until:
                        rows.append(
                            [
                                t,
                                r["opening_price"],
                                r["high_price"],
                                r["low_price"],
                                r["trade_price"],
                                r["candle_acc_trade_volume"],
                            ]
                        )
            except (KeyError, TypeError) as exc:
                raise DataError("Malformed Upbit candle response") from exc
            cursor = oldest
            time.sleep(self.delay)
        return normalize(rows, timeframe, timestamp_unit=None)
