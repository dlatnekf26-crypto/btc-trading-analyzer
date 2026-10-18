"""Shared market identities; adding an asset does not copy the dashboard."""

from dataclasses import dataclass
from datetime import date
import re


@dataclass(frozen=True)
class Asset:
    code: str
    name: str
    card_id: str
    decimals: int
    listed: date
    news_pattern: str
    pair: str | None = None

    @property
    def symbol(self):
        return self.pair or f"{self.code}/USDT"

    @property
    def stream_symbol(self):
        return self.pair or f"{self.code}USDT"


ASSETS = {
    asset.code: asset
    for asset in (
        Asset("BTC", "비트코인", "binance", 2, date(2017, 8, 17), r"\bBTC\b|bitcoin|비트코인"),
        Asset("ETH", "이더리움", "ethereum", 2, date(2017, 8, 17), r"\bETH\b|ethereum|이더리움"),
        Asset("SOL", "솔라나", "solana", 2, date(2020, 8, 11), r"\bSOL\b|solana|솔라나"),
        Asset("XRP", "리플", "ripple", 4, date(2018, 5, 4), r"\bXRP\b|ripple(?!\s+effects?\b)|리플"),
    )
}


STOCK_MARKETS = {
    asset.code: asset
    for asset in (
        Asset("SAMSUNG", "삼성전자", "macro-samsung", 0, date(1975, 6, 11), "", "005930.KS"),
        Asset("SKHYNIX", "SK하이닉스", "macro-skhynix", 0, date(1996, 12, 26), "", "000660.KS"),
        Asset("SAMSUNG_EM", "삼성전기", "macro-samsungem", 0, date(1979, 2, 27), "", "009150.KS"),
        Asset("LS_ELECTRIC", "LS일렉트릭", "macro-lselectric", 0, date(1994, 7, 11), "", "010120.KS"),
        Asset("AAPL", "애플", "macro-aapl", 2, date(1980, 12, 12), "", "AAPL"),
        Asset("NVDA", "엔비디아", "macro-nvda", 2, date(1999, 1, 22), "", "NVDA"),
        Asset("MU", "마이크론", "macro-mu", 2, date(1984, 6, 1), "", "MU"),
        Asset("SNDK", "샌디스크", "macro-sndk", 2, date(2025, 2, 13), "", "SNDK"),
    )
}
INDEX_MARKETS = {
    "NQ": Asset("NQ", "나스닥100 선물", "macro-nq", 2, date(1999, 6, 21), "", "NQ=F"),
    "KOSPI": Asset("KOSPI", "코스피", "macro-kospi", 2, date(1999, 1, 1), "", "^KS11"),
    "SP500": Asset("SP500", "S&P 500", "macro-sp500", 2, date(1957, 3, 4), "", "^GSPC"),
}
SESSION_MARKETS = {**INDEX_MARKETS, **STOCK_MARKETS}
MARKETS = {**ASSETS, **SESSION_MARKETS}


@dataclass(frozen=True)
class ExchangeHistory:
    currency: str
    timezone: str
    exchange: str
    source: str
    calendar: str = "CME_Equity"
    kind: str = "FUTURE"
    unit: str = "pt"


EXCHANGE_HISTORY = {
    "NQ": ExchangeHistory("USD", "America/New_York", "CME", "CME NQ 연속 선물"),
    "KOSPI": ExchangeHistory("KRW", "Asia/Seoul", "KRX", "KRX 코스피 종합지수", "KRX", "INDEX"),
    "SP500": ExchangeHistory("USD", "America/New_York", "S&P", "S&P 500 현물지수", "NYSE", "INDEX"),
    **{
        code: ExchangeHistory("KRW", "Asia/Seoul", "KRX", "KRX 보통주", "KRX", "EQUITY", "KRW")
        for code in ("SAMSUNG", "SKHYNIX", "SAMSUNG_EM", "LS_ELECTRIC")
    },
    **{
        code: ExchangeHistory(
            "USD", "America/New_York", "NASDAQ", "NASDAQ 정규장 주식", "NYSE", "EQUITY", "USD"
        )
        for code in ("AAPL", "NVDA", "MU", "SNDK")
    },
}


def market_label(code):
    venue = EXCHANGE_HISTORY.get(code)
    return MARKETS[code].name if code == "SP500" or venue and venue.calendar == "KRX" else code


def asset_news(title):
    """An explicit coin headline belongs only to that coin; generic crypto to all."""
    matches = tuple(code for code, asset in ASSETS.items() if re.search(asset.news_pattern, title, re.I))
    if matches:
        return matches
    if re.search(r"dogecoin|\bdoge\b|도지|cardano|\bADA\b|카르다노", title, re.I):
        return ()
    return tuple(ASSETS)


def price_text(value, signed=False):
    """Keep small asset levels readable without rounding to whole dollars."""
    places = 6 if 0 < abs(value) < 0.01 else 4 if abs(value) < 10 else 2
    return format(value, f"{'+' if signed else ''},.{places}f")
