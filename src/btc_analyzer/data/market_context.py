"""Bounded, nonblocking public macro quotes and headline feeds; no trading keys."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
from threading import RLock
import time
from urllib.parse import quote, urlencode, urlsplit
from xml.etree import ElementTree

import requests

from btc_analyzer.data.economic_calendar import EconomicEvent
from btc_analyzer.data.sentiment import FEAR_API, FEAR_REFRESH_SECONDS, FearGreed, parse_fear_greed

UTC = timezone.utc
MAX_BYTES = 512_000
NEWS_MAX_AGE = timedelta(hours=24)
QUOTE_REFRESH_SECONDS = 10
NEWS_REFRESH_SECONDS = 30
SYMBOLS = {"nq": "NQ=F", "tnx": "^TNX", "fx": "KRW=X", "oil": "CL=F", "tyx": "^TYX"}
TOPICS = {
    "oil": "유가",
    "geopolitics": "전쟁·지정학",
    "rates": "금리·연준",
    "inflation": "물가",
    "economy": "경제지표",
    "crypto": "코인 수급·규제",
}


@dataclass(frozen=True)
class MacroQuote:
    symbol: str
    price: float
    as_of: datetime
    fetched_at: datetime
    points: tuple[float, ...]
    change: float | None
    delay_minutes: int | None


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: datetime
    topic: str
    direction: int
    uncertainty: float
    explanation: str
    pending: bool = False


@dataclass(frozen=True)
class FeedState:
    key: str
    value: MacroQuote | FearGreed | tuple[NewsItem, ...] | tuple[EconomicEvent, ...] | None = None
    updated_at: datetime | None = None
    error: str = ""
    loading: bool = False


@dataclass(frozen=True)
class MarketContext:
    feeds: tuple[FeedState, ...] = ()

    def feed(self, key: str) -> FeedState:
        return next((f for f in self.feeds if f.key == key), FeedState(key))

    def news(self, now: datetime, *, fresh_only: bool = False) -> tuple[NewsItem, ...]:
        items = []
        for feed in self.feeds:
            if not feed.key.startswith("news") or not isinstance(feed.value, tuple):
                continue
            if fresh_only and (
                feed.updated_at is None or not timedelta(0) <= now - feed.updated_at <= timedelta(minutes=10)
            ):
                continue
            items.extend(
                item
                for item in feed.value
                if timedelta(0) <= now - item.published_at <= NEWS_MAX_AGE and crypto_relevance(item.title)
            )
        return deduplicate_news(items)


def _finite_positive(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("Invalid quote")
    return float(value)


def parse_quote(payload: dict, symbol: str, now: datetime) -> MacroQuote:
    """NQ points, WTI USD/barrel, CBOE 10/30-year yield % (never /10)."""
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    if symbol not in SYMBOLS.values() or meta["symbol"] != symbol:
        raise ValueError("Unexpected instrument")
    if symbol in ("NQ=F", "CL=F") and (
        meta.get("instrumentType", "FUTURE") != "FUTURE" or meta.get("currency", "USD") != "USD"
    ):
        raise ValueError("Expected USD futures")
    if symbol in ("^TNX", "^TYX") and (
        meta.get("instrumentType", "INDEX") != "INDEX" or meta.get("currency", "USD") != "USD"
    ):
        raise ValueError("Expected Treasury yield index")
    if symbol == "KRW=X" and (meta.get("instrumentType") != "CURRENCY" or meta.get("currency") != "KRW"):
        raise ValueError("Expected USD/KRW market quote")
    price = _finite_positive(meta["regularMarketPrice"])
    if symbol in ("^TNX", "^TYX") and price > 30:
        raise ValueError("Unrecognized yield units")
    as_of = datetime.fromtimestamp(_finite_positive(meta["regularMarketTime"]), UTC)
    if not timedelta(0) <= now - as_of <= timedelta(days=7):
        raise ValueError("Invalid quote time")
    stamps = result.get("timestamp") or []
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    points = []
    for stamp, close in zip(stamps, closes):
        if isinstance(stamp, (int, float)) and as_of.timestamp() - 7 * 86400 <= stamp <= as_of.timestamp():
            try:
                points.append(_finite_positive(close))
            except ValueError:
                pass
    previous = meta.get("chartPreviousClose", meta.get("previousClose"))
    try:
        change = price / _finite_positive(previous) - 1
    except ValueError:
        change = None
    delay = meta.get("exchangeDataDelayedBy")
    delay = (
        int(delay)
        if not isinstance(delay, bool)
        and isinstance(delay, (int, float))
        and math.isfinite(delay)
        and 0 <= delay <= 1440
        else None
    )
    return MacroQuote(symbol, price, as_of, now, tuple(points[-60:]), change, delay)


def crypto_relevance(title: str) -> str | None:
    """Require an explicit coin connection and a market event, not generic macro news."""
    text = title.casefold()
    coin = r"bitcoin|ethereum|cryptocurrenc\w*|\bcrypto\b|\bbtc\b|\beth\b|비트코인|이더리움|암호화폐|가상(?:자산|화폐)|코인"
    if not re.search(coin, text):
        return None
    if re.search(
        rf"(?:{coin}).{{0,12}}(?:무관|영향 없)|(?:unrelated to|no impact on).{{0,12}}(?:{coin})", text
    ):
        return None
    if not re.search(
        r"price|rall|surge|jump|drop|fall|crash|rise|rising|market|liquidat|inflow|outflow|\betf\b|\bsec\b|regulat|hack|exchange|adopt|supply|demand|reserve|rates?|\bfed\b|\bcpi\b|\bpce\b|inflation|payroll|\bgdp\b|oil|war|ceasefire|가격|시세|상승|하락|급등|급락|청산|수급|유입|유출|규제|해킹|거래소|매수|매도|금리|연준|물가|고용|유가|원유|전쟁|휴전|공습|미사일",
        text,
    ):
        return None
    if re.search(r"oil|crude|유가|원유", text):
        return "유가·물가 부담과 코인 시장을 연결한 소식"
    if re.search(r"\bfed\b|rates?|inflation|\bcpi\b|\bpce\b|연준|금리|물가|고용", text):
        return "금리·경제지표와 코인 시장을 연결한 소식"
    if re.search(r"war|ceasefire|전쟁|휴전|공습|미사일", text):
        return "지정학 위험과 코인 시장을 연결한 소식"
    return "코인 가격·수급·규제와 연결된 소식"


def classify_headline(title: str):
    """Conservative title-only rules, not article verification or trained sentiment."""
    text = title.casefold()
    if re.search(r"\boil\b|\bcrude\b|\bwti\b|\bbrent\b|유가|원유", text):
        topic = "oil"
    elif re.search(r"\bcpi\b|\bpce\b|inflation|물가|인플레이션", text):
        topic = "inflation"
    elif re.search(r"\bfed\b|federal reserve|rate cut|rate hike|연준|금리", text):
        topic = "rates"
    elif re.search(r"\bwar\b|ceasefire|missile|strike|conflict|전쟁|휴전|공습|미사일|중동", text):
        topic = "geopolitics"
    elif re.search(r"payroll|jobs report|unemployment|\bgdp\b|고용|실업|경제지표", text):
        topic = "economy"
    elif re.search(
        r"bitcoin|ethereum|\bbtc\b|\beth\b|\bcrypto\b|비트코인|이더리움|암호화폐|가상자산|\betf\b", text
    ):
        topic = "crypto"
    else:
        return None
    pending = bool(
        re.search(
            r"ahead of|awaits?|preview|upcoming|scheduled|expected to|could|may cut|may hike|cut bets|cut odds|considers?|weighs?|발표 예정|발표예정|앞두고|전망|가능성|예상된다|금리.{0,5}(?:인하|인상).{0,8}(?:기대|관측|베팅)",
            text,
        )
    )
    if pending:
        return topic, 0, 1.0, "발표·전개 대기: 실제 결과를 알 수 없어 방향 대신 불확실성만 반영해요.", True
    up = bool(
        re.search(
            r"surges?|jumps?|rall(?:y|ies)|spikes?|soars?|rises?|rising|higher|급등|상승|올라|인상", text
        )
    )
    down = bool(re.search(r"falls?|drops?|declines?|plunges?|slides?|lower|급락|하락|내려|인하", text))
    negated = bool(re.search(r"\bnot\b|\bno\b|denies?|fails?|cancel|ruled out|무산|부인|취소|않|아니", text))
    direction, uncertainty, explanation = 0, 0.5, "제목만으로 BTC에 미치는 방향을 확정하기 어려워요."
    if not negated:
        if topic == "oil" and up != down:
            direction = -1 if up else 1
            explanation = "유가 상승은 물가·금리 부담, 하락은 부담 완화로 작용할 수 있어요."
        elif topic == "inflation":
            hot = bool(
                re.search(
                    r"hotter than|above (?:forecasts?|expectations?)|higher than expected|예상(?:보다|치) (?:높|상회)|예상치 상회",
                    text,
                )
            )
            cool = bool(
                re.search(
                    r"cooler than|below (?:forecasts?|expectations?)|lower than expected|예상(?:보다|치) (?:낮|하회)|예상치 하회",
                    text,
                )
            )
            if hot != cool:
                direction = -1 if hot else 1
                explanation = "예상을 웃돈 물가는 긴축 부담, 밑돈 물가는 완화 기대를 만들 수 있어요."
        elif topic == "rates":
            cut = bool(re.search(r"cuts? (?:interest )?rates?|rate cuts?|금리.{0,5}인하", text))
            hike = bool(re.search(r"hikes? (?:interest )?rates?|rate hikes?|금리.{0,5}인상", text))
            if cut != hike:
                direction = 1 if cut else -1
                explanation = "금리 인하는 유동성에 우호적, 인상은 부담일 수 있어요. 경기침체성 인하는 다르게 움직일 수 있습니다."
        elif topic == "geopolitics":
            peace = bool(
                re.search(
                    r"ceasefire (?:agreed|agreement|deal)|agree.{0,12}ceasefire|peace deal|휴전.{0,5}(?:합의|체결)|종전.{0,5}합의",
                    text,
                )
            )
            escalation = bool(
                re.search(
                    r"escalat|missile|airstrike|launch.{0,10}attack|전쟁.{0,5}(?:확대|발발)|공습|미사일", text
                )
            )
            if peace != escalation:
                direction = 1 if peace else -1
                explanation = "휴전 합의는 위험 완화, 충돌 확대는 위험자산 부담으로 작용할 수 있어요."
        elif topic == "crypto":
            inflow = bool(re.search(r"\binflows?\b|순유입", text))
            outflow = bool(re.search(r"\boutflows?\b|순유출|hack|해킹", text))
            if inflow != outflow:
                direction = 1 if inflow else -1
                explanation = "자금 유입은 수요에 우호적, 유출·해킹은 부담일 수 있어요."
    return topic, direction, uncertainty, explanation, False


def deduplicate_news(items) -> tuple[NewsItem, ...]:
    unique = {}
    for item in items:
        key = re.sub(r"\W+", "", item.title.casefold())
        if key not in unique or item.published_at > unique[key].published_at:
            unique[key] = item
    return tuple(sorted(unique.values(), key=lambda item: item.published_at, reverse=True)[:40])


def parse_news(raw: bytes, now: datetime) -> tuple[NewsItem, ...]:
    if len(raw) > MAX_BYTES or re.search(rb"<!DOCTYPE|<!ENTITY", raw, re.I):
        raise ValueError("Unsupported feed")
    items = []
    for node in ElementTree.fromstring(raw).findall("./channel/item")[:100]:
        try:
            title = " ".join((node.findtext("title") or "").split())[:320]
            source = " ".join((node.findtext("source") or "출처 미표기").split())[:80]
            # Syndicated source names must not change the headline classification.
            if title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            if not crypto_relevance(title):
                continue
            url = node.findtext("link") or ""
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "news.google.com"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                continue
            published = parsedate_to_datetime(node.findtext("pubDate") or "")
            if published.tzinfo is None:
                continue
            published = published.astimezone(UTC)
            if not timedelta(0) <= now - published <= NEWS_MAX_AGE:
                continue
            classification = classify_headline(title)
            if classification:
                topic, direction, uncertainty, explanation, pending = classification
                items.append(
                    NewsItem(
                        title, url, source, published, topic, direction, uncertainty, explanation, pending
                    )
                )
        except (ValueError, TypeError, OverflowError):
            continue
    return deduplicate_news(items)


def _download(url: str) -> bytes:
    # Bounded streams retain the platform proxy/TLS checks and never follow off-host redirects.
    with requests.get(
        url,
        timeout=(2, 3),
        stream=True,
        allow_redirects=False,
        headers={"User-Agent": "Mozilla/5.0 BTC-Signal-Lab/1.0"},
    ) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Unexpected response")
        parts, size, started = [], 0, time.monotonic()
        for part in response.iter_content(16_384):
            size += len(part)
            if size > MAX_BYTES or time.monotonic() - started > 5:
                raise ValueError("Response limit exceeded")
            parts.append(part)
        return b"".join(parts)


def fetch_feed(key: str, now: datetime):
    if key == "fear":
        return parse_fear_greed(json.loads(_download(FEAR_API)), now)
    if key in SYMBOLS:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(SYMBOLS[key], safe='')}?interval=1m&range=1d"
        return parse_quote(json.loads(_download(url)), SYMBOLS[key], now)
    language = "ko" if key == "news_ko" else "en-US"
    query = (
        "(비트코인 OR 이더리움 OR 암호화폐 OR 가상자산) (ETF OR 규제 OR 수급 OR 가격 OR 금리 OR CPI OR 유가 OR 전쟁) when:1d"
        if key == "news_ko"
        else "(bitcoin OR ethereum OR cryptocurrency OR crypto) (ETF OR regulation OR inflows OR price OR Fed OR CPI OR oil OR war) when:1d"
    )
    params = urlencode(
        {
            "q": query,
            "hl": language,
            "gl": "KR" if key == "news_ko" else "US",
            "ceid": "KR:ko" if key == "news_ko" else "US:en",
        }
    )
    return parse_news(_download("https://news.google.com/rss/search?" + params), now)


class MarketContextService:
    """Shared resources: one in-flight request per feed, independent last-good results."""

    def __init__(
        self,
        fetcher=fetch_feed,
        clock=lambda: datetime.now(UTC),
        *,
        keys=None,
        refresh_intervals=None,
        workers=4,
    ):
        self._fetcher, self._clock = fetcher, clock
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="market-context")
        self._states = {
            key: FeedState(key)
            for key in (keys if keys is not None else (*SYMBOLS, "news_ko", "news_en", "fear"))
        }
        self._refresh_intervals = refresh_intervals or {}
        self._next = dict.fromkeys(self._states, datetime.min.replace(tzinfo=UTC))
        self._failures = dict.fromkeys(self._states, 0)
        self._closed = False

    def snapshot(self) -> MarketContext:
        now = self._clock()
        with self._lock:
            for key, state in tuple(self._states.items()):
                if not self._closed and not state.loading and now >= self._next[key]:
                    self._states[key] = FeedState(key, state.value, state.updated_at, state.error, True)
                    future = self._executor.submit(self._fetcher, key, now)
                    future.add_done_callback(lambda result, key=key: self._complete(key, result))
            return MarketContext(tuple(self._states.values()))

    def _complete(self, key, future):
        now = self._clock()
        with self._lock:
            old = self._states[key]
            try:
                value = future.result()
                self._states[key] = FeedState(key, value, now)
                self._failures[key] = 0
                delay = NEWS_REFRESH_SECONDS if key.startswith("news") else QUOTE_REFRESH_SECONDS
                if key == "fear":
                    delay = FEAR_REFRESH_SECONDS
                    if isinstance(value, FearGreed) and value.next_update is not None:
                        delay = min(delay, max(60, (value.next_update - now).total_seconds()))
                delay = self._refresh_intervals.get(key, delay)
            except Exception as exc:
                self._failures[key] += 1
                delay = min(1800, 60 * 2 ** min(self._failures[key] - 1, 5))
                delay = max(delay, self._refresh_intervals.get(key, 0))
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    retry = exc.response.headers.get("Retry-After", "")
                    if retry.isdigit():
                        delay = max(delay, min(int(retry), 3600))
                # No raw provider payload/error body/credentials shown in the UI.
                self._states[key] = FeedState(key, old.value, old.updated_at, "자료원 연결 지연")
            self._next[key] = now + timedelta(seconds=delay)

    def close(self):
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
