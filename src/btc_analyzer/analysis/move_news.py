"""Fresh source-linked catalyst candidates; headline timing is not causation."""

from datetime import timedelta
from html import escape
import re
from urllib.parse import urlsplit

from btc_analyzer.data.market_context import crypto_relevance

CATALYST = re.compile(
    r"\b(?:ETF|inflows?|outflows?|hacks?|hacked|hacking|exploits?|SEC|Fed|FOMC|CPI|PCE|PPI|"
    r"oil|crude|war|ceasefire|tariffs?|payroll|inflation|approval|approved)\b|"
    r"\b(?:regulat\w*|lawsuits?|liquidat\w*|interest.rates?)\b|"
    r"유입|유출|해킹|규제|소송|청산|금리|연준|물가|유가|원유|전쟁|중동|휴전|관세|고용|승인",
    re.I,
)


def news_bridge(context, now):
    links, seen = [], set()
    for feed in context.feeds:
        if (
            not feed.key.startswith("news")
            or not isinstance(feed.value, tuple)
            or feed.error
            or feed.updated_at is None
            or not timedelta(0) <= now - feed.updated_at <= timedelta(minutes=2)
        ):
            continue
        for item in feed.value:
            if (
                item.pending
                or re.search(r"rumou?r|unconfirmed|alleged|루머|미확인|소문", item.title, re.I)
                or item.url in seen
                or not crypto_relevance(item.title)
                or not CATALYST.search(item.title)
                or not timedelta(0) <= now - item.published_at <= timedelta(minutes=30)
                or urlsplit(item.url).scheme not in ("http", "https")
                or not urlsplit(item.url).netloc
            ):
                continue
            btc = bool(re.search(r"\bBTC\b|bitcoin|비트코인", item.title, re.I))
            eth = bool(re.search(r"\bETH\b|ethereum|이더리움", item.title, re.I))
            assets = " ".join(symbol for symbol, match in (("BTCUSDT", btc), ("ETHUSDT", eth)) if match)
            if not assets:
                if re.search(
                    r"solana|\bsol\b|xrp|ripple|dogecoin|\bdoge\b|솔라나|리플|도지", item.title, re.I
                ):
                    continue
                assets = "BTCUSDT ETHUSDT"
            seen.add(item.url)
            links.append(
                (
                    item.published_at,
                    f'<a href="{escape(item.url, quote=True)}" data-assets="{assets}" data-direction="{item.direction}" data-published="{int(item.published_at.timestamp() * 1000)}" data-fetched="{int(feed.updated_at.timestamp() * 1000)}" data-source="{escape(item.source, quote=True)}">{escape(item.title)}</a>',
                )
            )
    links.sort(key=lambda entry: entry[0], reverse=True)
    return '<div hidden id="btc-news-bridge">' + "".join(link for _, link in links[:24]) + "</div>"
