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

    @property
    def symbol(self):
        return f"{self.code}/USDT"

    @property
    def stream_symbol(self):
        return f"{self.code}USDT"


ASSETS = {
    asset.code: asset
    for asset in (
        Asset("BTC", "비트코인", "binance", 2, date(2017, 8, 17), r"\bBTC\b|bitcoin|비트코인"),
        Asset("ETH", "이더리움", "ethereum", 2, date(2017, 8, 17), r"\bETH\b|ethereum|이더리움"),
        Asset("SOL", "솔라나", "solana", 2, date(2020, 8, 11), r"\bSOL\b|solana|솔라나"),
        Asset("XRP", "리플", "ripple", 4, date(2018, 5, 4), r"\bXRP\b|ripple(?!\s+effects?\b)|리플"),
    )
}


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
