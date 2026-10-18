"""Lightweight quote board and a shared, browser-updated detail heading."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st
from btc_analyzer.assets import ASSETS, MARKETS, SESSION_MARKETS
from btc_analyzer.data.market_context import MacroQuote, UTC
from btc_analyzer.ui.browser_assets import browser_asset
from btc_analyzer.ui.market_context import current_context, render_macro_quotes

BOARD_CSS = "<style>" + browser_asset("board.css") + "</style>"
COLORS = {
    "BTC": "#f3a712",
    "ETH": "#6574cf",
    "SOL": "#15aa8b",
    "XRP": "#377de0",
    "NQ": "#9b6fd4",
    "KOSPI": "#ef789e",
}
ICONS = {"BTC": "₿", "ETH": "Ξ", "SOL": "◎", "XRP": "X", "NQ": "N", "KOSPI": "K"}


def asset_identity(code):
    color = COLORS.get(code, "#377de0")
    icon = ICONS.get(code, escape(code[:1]))
    return (
        f'<span class="board-icon" style="--asset-color:{color}">{icon}</span>'
        f'<div><strong>{MARKETS[code].name}</strong><span class="board-symbol">{code}</span></div>'
    )


def quote_fields(code, *, detail=False, context=None):
    asset = MARKETS[code]
    session = code in SESSION_MARKETS
    attributes, price, change, status, direction = "", "—", "변동률 대기", "시세 연결 중…", ""
    if session:
        value = context.feed(asset.card_id.removeprefix("macro-")).value if context else None
        if isinstance(value, MacroQuote) and timedelta(0) <= datetime.now(UTC) - value.as_of <= timedelta(
            days=7
        ):
            price = f"{value.price:,.2f}"
            change = f"{value.change:+.2%}" if value.change is not None else change
            stamp = value.as_of.astimezone(ZoneInfo("Asia/Seoul"))
            old = datetime.now(UTC) - value.as_of > timedelta(hours=2)
            prefix = "마지막 거래" if old else "공개 조회"
            status = f"{prefix} · {stamp:%m.%d %H:%M} KST · 지연 " + (
                f"{value.delay_minutes}분" if value.delay_minutes is not None else "미확인"
            )
            if context.feed(asset.card_id.removeprefix("macro-")).error:
                status += " · 갱신 지연"
            direction = (
                "up"
                if value.change is not None and value.change >= 0
                else "down"
                if value.change is not None
                else ""
            )
            attributes = (
                f' data-symbol="{escape(value.symbol)}" data-price="{value.price}"'
                f' data-asof="{int(value.as_of.timestamp() * 1000)}"'
                f' data-fetched="{int(value.fetched_at.timestamp() * 1000)}"'
                f' data-delay="{value.delay_minutes if value.delay_minutes is not None else -1}"'
                f' data-points="{",".join(str(p) for p in value.points)}"'
            )
    macro_id = f' id="{asset.card_id}"' if session and not detail else ""
    source = "KRX 코스피 · pt" if code == "KOSPI" else "CME NQ · pt" if session else "Binance · USDT"
    classes = "board-detail" if detail else "board-asset" + (" btc-macro-card" if session else "")
    heading = f'<div class="board-identity">{asset_identity(code)}</div>'
    metrics = ""
    if not detail:
        if session:
            metrics = (
                '<div class="board-session-info"><span>가격 기준</span><b>공개 거래소 시세</b>'
                "<span>분석 시간대</span><b>5분 ~ 월봉</b><span>미래 예측</span><b>1주 ~ 6개월</b></div>"
                '<div class="btc-macro-graph board-spark"></div>'
                '<span class="btc-macro-badge board-source">연결 확인 중</span>'
            )
        else:
            metrics = (
                '<div class="board-metrics"><span>24시간 고가</span><b data-quote-field="high">—</b>'
                '<span>24시간 저가</span><b data-quote-field="low">—</b>'
                '<span>거래량</span><b data-quote-field="volume">—</b>'
                '<span>거래대금 · USDT</span><b data-quote-field="turnover">—</b></div>'
                '<div class="board-range" role="img" aria-label="24시간 저가·고가 사이 현재 가격 위치">'
                '<i data-quote-field="position" hidden></i></div>'
                '<div class="board-range-label"><span>24시간 저가</span><span>고가</span></div>'
            )
        metrics += '<div class="board-open">차트 · 분석 · 미래 예측 <span>↗</span></div>'
    return (
        f'<article class="{classes}"{macro_id}{attributes} data-quote-symbol="{escape(asset.stream_symbol)}" data-status="pending">'
        + heading
        + f'<div class="board-status btc-macro-status" data-quote-field="status">{status}</div>'
        + f'<div class="board-price"><b class="btc-macro-value" data-quote-field="price">{price}</b><small>{source}</small></div>'
        + f'<div class="board-change btc-macro-change" data-quote-field="change" data-direction="{direction}">{change}</div>'
        + metrics
        + "</article>"
    )


def detail_heading(code):
    return quote_fields(code, detail=True)


def section_heading(title, count, subtitle):
    st.markdown(
        f'<div class="board-section"><h2>{title}<small>{count}</small></h2><span>{subtitle}</span><i></i></div>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every=2)
def render_board_sentiment():
    context = current_context()
    value = context.feed("fear").value
    latest = getattr(value, "latest", None)
    if latest:
        stamp = latest.timestamp.astimezone(ZoneInfo("Asia/Seoul"))
        old = not timedelta(0) <= datetime.now(UTC) - latest.timestamp <= timedelta(hours=48)
        label = "마지막 값" if old or context.feed("fear").error else "일별 발표"
        score = latest.value
        st.markdown(
            f'<div class="board-sentiment"><span>코인 공포·탐욕</span><b>{score}</b>'
            f'<div class="board-gauge" style="--score:{score}%"><i></i></div>'
            f"<small>{label} · {stamp:%m.%d} · Alternative.me</small></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="board-sentiment"><span>코인 공포·탐욕</span><b>—</b><small>원자료 연결 대기 · 일별 발표</small></div>',
            unsafe_allow_html=True,
        )


def market_columns(codes):
    """Wrap added markets into another row instead of truncating the catalog."""
    values = list(codes)
    for start in range(0, len(values), 4):
        yield from zip(st.columns(4, gap="small"), values[start : start + 4])


def render_board(on_open):
    st.markdown(
        '<div class="board-topline"><div class="board-pill"><i></i>코인 24시간 거래</div>'
        "<span>가격은 실시간으로 · 판단은 근거와 함께</span></div>",
        unsafe_allow_html=True,
    )
    with st.container(key="board_overview"):
        sentiment, fx, premium = st.columns([2, 1.2, 1.2])
        with sentiment:
            render_board_sentiment()
        with fx:
            st.markdown(
                '<div class="board-fx" data-reference="fx"><span>원·달러 환율 <small>USD/KRW</small></span><b data-reference-field="price">—</b><small data-reference-field="status">자료 연결 중</small></div>',
                unsafe_allow_html=True,
            )
        with premium:
            st.markdown(
                '<div class="board-fx" data-reference="premium"><span>김치프리미엄 <small>BTC</small></span><b data-reference-field="price">—</b><small data-reference-field="status">환산 시세 연결 중</small></div>',
                unsafe_allow_html=True,
            )
    st.markdown(
        '<div class="board-nav"><b>전체 시세</b><span>종목을 누르면 상세 차트가 열려요</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="board_macro"):
        render_macro_quotes(("oil", "tnx", "tyx"))
    section_heading("암호화폐", len(ASSETS), "Binance · 24시간 등락률")
    with st.container(key="board_coins"):
        for column, code in market_columns(ASSETS):
            with column, st.container(key=f"board_card_{code}"):
                st.markdown(quote_fields(code), unsafe_allow_html=True)
                st.button(
                    f"{MARKETS[code].name} 차트 열기",
                    key=f"open_{code}",
                    on_click=on_open,
                    args=(code,),
                    width="stretch",
                )
    section_heading("지수 · 선물", len(SESSION_MARKETS), "거래소 운영 시간 · 공개 자료 지연 별도")
    with st.container(key="board_sessions"):
        render_session_cards(on_open)
    st.markdown(
        '<p class="board-footnote">수신 시각과 지연 상태를 함께 확인하세요. 예측은 과거 자료·기술 지표에 기반한 시나리오예요.</p>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every=2)
def render_session_cards(on_open):
    context = current_context()
    for column, code in market_columns(SESSION_MARKETS):
        with column, st.container(key=f"board_card_{code}"):
            st.markdown(quote_fields(code, context=context), unsafe_allow_html=True)
            if st.button(f"{MARKETS[code].name} 차트 열기", key=f"open_{code}", width="stretch"):
                on_open(code)
                st.rerun(scope="app")
