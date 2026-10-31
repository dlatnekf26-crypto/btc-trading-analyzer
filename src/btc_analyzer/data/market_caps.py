"""Published capitalizations only; compare within the board's currency groups."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from urllib.parse import quote, urlencode

from btc_analyzer.assets import STOCK_MARKETS, EXCHANGE_HISTORY, COIN_IDS


@dataclass(frozen=True)
class Capitalization:
    value: float
    currency: str
    date: str


def parse_cap(payload, code, now):
    asset, venue = STOCK_MARKETS[code], EXCHANGE_HISTORY[code]
    candidates = []
    for result in payload.get("timeseries", {}).get("result") or []:
        if result.get("meta", {}).get("symbol") != [asset.symbol]:
            continue
        for row in result.get("trailingMarketCap", []):
            stamp = datetime.strptime(row["asOfDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            value = row.get("reportedValue", {}).get("raw")
            if (
                row.get("currencyCode") == venue.currency
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0
                and timedelta(0) <= now - stamp <= timedelta(days=180)
            ):
                candidates.append(Capitalization(value, venue.currency, row["asOfDate"]))
    return max(candidates, key=lambda cap: cap.date, default=None)


def fetch_caps(now):
    from btc_analyzer.data.market_context import _download

    def stock(code):
        params = urlencode(
            dict(
                type="trailingMarketCap",
                period1=int((now - timedelta(days=190)).timestamp()),
                period2=int(now.timestamp()),
            )
        )
        url = (
            "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
            + quote(STOCK_MARKETS[code].symbol, safe="")
            + "?"
            + params
        )
        try:
            return code, parse_cap(json.loads(_download(url)), code, now)
        except (ValueError, KeyError, TypeError, OSError):
            return code, None

    with ThreadPoolExecutor(max_workers=3) as pool:
        caps = {code: value for code, value in pool.map(stock, STOCK_MARKETS) if value is not None}
    try:
        rows = json.loads(
            _download(
                "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + ",".join(COIN_IDS)
            )
        )
        ids = COIN_IDS
        if not isinstance(rows, list):
            raise ValueError("Invalid coin capitalization response")
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = ids.get(row.get("id"))
            value = row.get("market_cap")
            at = datetime.fromisoformat(row["last_updated"].replace("Z", "+00:00"))
            if (
                code
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0
                and at.tzinfo
                and timedelta(0) <= now - at <= timedelta(days=2)
            ):
                caps[code] = Capitalization(value, "USD", at.date().isoformat())
    except (ValueError, KeyError, TypeError, OSError):
        pass
    if not caps:
        raise ValueError("Market capitalizations unavailable")
    return caps


def cap_order(codes, caps):
    return sorted(codes, key=lambda code: (code not in caps, -caps[code].value if code in caps else 0))
