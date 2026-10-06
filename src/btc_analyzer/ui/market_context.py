"""Independent native macro/news fragment; crypto sockets are never recreated."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from btc_analyzer import __checkout_signature__
from btc_analyzer.data.market_context import MarketContextService, MacroQuote, TOPICS, UTC, crypto_relevance

CONTEXT_CSS = """<style>
.btc-macro-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0 0 12px}
.btc-macro-card,.btc-news-item{background:linear-gradient(135deg,#fff,#f9fbff);border:1px solid #e7ecf3;border-radius:20px;padding:16px;min-width:0}
.btc-macro-name{font-size:14px;font-weight:700;margin:0 0 6px;color:#191f28}.btc-macro-value{font-size:26px;font-weight:750;letter-spacing:-.6px;font-variant-numeric:tabular-nums}
.btc-macro-card p{font-size:11px;color:#66758b;margin:5px 0}.btc-macro-card a,.btc-news-item a{color:#25496e;text-decoration:none}.btc-macro-card svg{width:100%;height:42px;display:block;margin:8px 0}
.btc-news-item{margin:8px 0;padding:14px 16px}.btc-news-title{font-size:15px;font-weight:650;line-height:1.55;display:block;margin:7px 0;overflow-wrap:anywhere}.btc-news-meta,.btc-news-explain{font-size:12px;color:#66758b;line-height:1.55;margin:4px 0}
.btc-news-badge{font-size:11px;display:inline-block;padding:3px 8px;border-radius:8px;background:#f0f3f8;color:#59677c;margin-right:6px}.btc-news-badge.up{background:#e7f6f0;color:#087f5b}.btc-news-badge.down{background:#fff0ed;color:#c44d40}
.btc-news-scenario{background:#f4f0ff;border:1px solid #e5ddfa;border-radius:16px;padding:14px 16px;font-size:13px;color:#665086;line-height:1.6;margin:12px 0;overflow-wrap:anywhere}
@media(max-width:450px){.btc-macro-card{padding:12px;border-radius:16px}.btc-macro-value{font-size:22px}.btc-macro-name{font-size:12px}.btc-news-title{font-size:14px}}
</style>"""


@st.cache_resource(show_spinner=False, max_entries=1, on_release=lambda service: service.close())
def cached_context_service(source_version):
    return MarketContextService()


def context_service():
    # A hot deployment reloads dataclass identities. Never reuse an older
    # generation's resource/quotes against the new module's type checks.
    return cached_context_service(__checkout_signature__)


def current_context():
    return context_service().snapshot()


def sparkline(points):
    if len(points) < 2:
        return "<p>그래프 자료 대기</p>"
    low, high = min(points), max(points)
    span = high - low or max(abs(low) * 0.001, 0.001)
    path = " ".join(
        f"{i * 240 / (len(points) - 1):.1f},{38 - (value - low) / span * 32:.1f}"
        for i, value in enumerate(points)
    )
    return f'<svg viewBox="0 0 240 42" role="img" aria-label="최근 거래 가격 그래프"><polyline points="{path}" fill="none" stroke="#3182f6" stroke-width="2" stroke-linejoin="round"/></svg>'


def macro_cards(context, now):
    cards = []
    for key, title, unit, link in (
        ("nq", "나스닥100 선물", "pt · NQ=F", "https://finance.yahoo.com/quote/NQ%3DF/"),
        ("tnx", "미국채 10년물", "% · 수익률 지표", "https://finance.yahoo.com/quote/%5ETNX/"),
    ):
        feed = context.feed(key)
        value = feed.value
        if isinstance(value, MacroQuote) and timedelta(0) <= now - value.as_of <= timedelta(days=7):
            stamp = value.as_of.astimezone(ZoneInfo("Asia/Seoul"))
            age = now - value.as_of
            status = "마지막 거래 시세" if age > timedelta(hours=2) else "지연 시세"
            if feed.error or (feed.updated_at and now - feed.updated_at > timedelta(minutes=3)):
                status += " · 갱신 지연"
            delay = (
                f" · 제공 지연 {value.delay_minutes}분"
                if value.delay_minutes is not None
                else " · 제공 지연 미확인"
            )
            price = f"{value.price:,.2f}"
            graph = sparkline(value.points)
            change = (
                "기준값 대기" if value.change is None else f"조회 구간 시작 종가 대비 {value.change:+.2%}"
            )
            info = f"{status} · {stamp:%m.%d %H:%M} KST{delay}"
        else:
            price, graph, change = "—", "<p>시세 자료를 기다리고 있어요</p>", "수신한 값만 표시해요"
            info = feed.error or "공개 자료원 연결 중…"
        source = "Yahoo Finance · CME 선물" if key == "nq" else "Yahoo Finance · CBOE ^TNX"
        attributes = ""
        if isinstance(value, MacroQuote):
            attributes = (
                f' data-symbol="{escape(value.symbol, quote=True)}" data-price="{value.price}"'
                f' data-asof="{int(value.as_of.timestamp() * 1000)}"'
                f' data-fetched="{int(value.fetched_at.timestamp() * 1000)}"'
                f' data-delay="{value.delay_minutes if value.delay_minutes is not None else -1}"'
                f' data-points="{",".join(str(point) for point in value.points)}"'
            )
        cards.append(
            f'<article class="btc-macro-card" id="macro-{key}"{attributes}><div class="btc-macro-name">{title}</div><div class="btc-macro-value">{price}</div><p class="btc-macro-change">{unit} · {escape(change)}</p><div class="btc-macro-graph">{graph}</div><p class="btc-macro-status">{escape(info)}</p><p><a href="{link}" target="_blank" rel="noopener noreferrer">{source} ↗</a></p></article>'
        )
    fx = context.feed("fx").value
    bridge = (
        f'<span hidden id="macro-fx-reference" data-symbol="KRW=X" data-price="{fx.price}" data-asof="{int(fx.as_of.timestamp() * 1000)}" data-fetched="{int(fx.fetched_at.timestamp() * 1000)}"></span>'
        if isinstance(fx, MacroQuote)
        else ""
    )
    return '<div class="btc-macro-grid" aria-label="대외 시장 시세">' + "".join(cards) + "</div>" + bridge


def news_card(item):
    direction = (
        "우호 가능"
        if item.direction > 0
        else "부담 가능"
        if item.direction < 0
        else "발표·전개 대기"
        if item.pending
        else "방향 미정"
    )
    color = "up" if item.direction > 0 else "down" if item.direction < 0 else ""
    stamp = item.published_at.astimezone(ZoneInfo("Asia/Seoul"))
    relevance = crypto_relevance(item.title) or ""
    return f'<article class="btc-news-item"><span class="btc-news-badge">{escape(TOPICS[item.topic])}</span><span class="btc-news-badge {color}">{direction}</span><a class="btc-news-title" href="{escape(item.url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(item.title)} ↗</a><p class="btc-news-meta">{escape(item.source)} · {stamp:%m.%d %H:%M} KST</p><p class="btc-news-explain">{escape(relevance)} · {escape(item.explanation)}</p></article>'


@st.fragment(run_every=2)
def render_macro_quotes():
    now = datetime.now(UTC)
    context = current_context()
    st.markdown(CONTEXT_CSS + macro_cards(context, now), unsafe_allow_html=True)


@st.fragment(run_every=15)
def render_coin_news():
    now = datetime.now(UTC)
    context = current_context()
    st.markdown("**코인에 영향을 주는 주요 뉴스**")
    st.caption("코인 수급·규제 + 코인과 연결된 금리·유가·전쟁 | 1분마다 자료 갱신")
    news = context.news(now)
    if not news:
        loading = any(feed.loading for feed in context.feeds if feed.key.startswith("news"))
        failed = any(feed.error for feed in context.feeds if feed.key.startswith("news"))
        st.caption(
            "주요 소식을 불러오는 중…"
            if loading
            else "뉴스 자료원 연결 지연 · 소식이 도착하면 표시해요."
            if failed
            else "최근 24시간의 코인 관련 소식이 아직 없습니다."
        )
        return
    # First screen covers distinct topics; a flood of one event does not hide all others.
    first, seen = [], set()
    for item in news:
        if item.topic not in seen:
            first.append(item)
            seen.add(item.topic)
        if len(first) == 3:
            break
    st.markdown("".join(news_card(item) for item in first), unsafe_allow_html=True)
    remaining = [item for item in news if item not in first]
    if remaining:
        with st.expander(f"주요 뉴스 더 보기 · {len(remaining)}건"):
            st.markdown("".join(news_card(item) for item in remaining[:9]), unsafe_allow_html=True)
    feeds = [f for f in context.feeds if f.key.startswith("news")]
    stamps = [f.updated_at for f in feeds if f.updated_at]
    if stamps:
        st.caption(
            f"자료 확인 {max(stamps).astimezone(ZoneInfo('Asia/Seoul')):%m.%d %H:%M} KST · "
            + (
                "일부 자료원 갱신 지연"
                if any(f.error for f in feeds)
                else "기사 원문에서 내용을 확인해 주세요."
            )
        )


def render_market_context():
    render_macro_quotes()
    render_coin_news()
