"""Lightweight quote board and a shared, browser-updated detail heading."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st
from btc_analyzer.assets import (
    ASSETS,
    MARKETS,
    SESSION_MARKETS,
    STOCK_MARKETS,
    INDEX_MARKETS,
    MACRO_MARKETS,
    EXCHANGE_HISTORY,
)
from btc_analyzer.data.market_context import MacroQuote, UTC
from btc_analyzer.ui.browser_assets import browser_asset
from btc_analyzer.ui.market_context import current_context
from btc_analyzer.ui.quote_snapshot import render_quote_snapshot, quote_display

BOARD_CSS = "<style>" + browser_asset("board.css") + "</style>"
COLORS = {
    "BTC": "#f3a712",
    "ETH": "#6574cf",
    "SOL": "#15aa8b",
    "XRP": "#377de0",
    "NQ": "#9b6fd4",
    "KOSPI": "#ef789e",
    "SAMSUNG": "#eaa400",
    "SKHYNIX": "#14b88c",
    "AAPL": "#397ddb",
    "NVDA": "#eb79a8",
    "MU": "#dfaa00",
    "SNDK": "#875ec2",
    "SAMSUNG_EM": "#4574db",
    "LS_ELECTRIC": "#12a080",
    "SP500": "#755ce0",
}
ICONS = {
    "BTC": "₿",
    "ETH": "Ξ",
    "SOL": "◎",
    "XRP": "X",
    "NQ": "N",
    "KOSPI": "K",
    "SAMSUNG": "삼",
    "SKHYNIX": "S",
    "AAPL": "애",
    "NVDA": "엔",
    "MU": "마",
    "SNDK": "샌",
    "SAMSUNG_EM": "전",
    "LS_ELECTRIC": "LS",
    "SP500": "S",
}


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
    value = None
    if session:
        feed = context.feed(asset.card_id.removeprefix("macro-")) if context else None
        value = feed.value if feed else None
        if isinstance(value, MacroQuote) and value.symbol != asset.symbol:
            value = None
        if feed and feed.error:
            status = feed.error + " · 자동 재시도 중"
        if isinstance(value, MacroQuote) and timedelta(0) <= datetime.now(UTC) - value.as_of <= timedelta(
            days=7
        ):
            display = quote_display(value)
            prefix = (
                "₩" if code in STOCK_MARKETS and asset.decimals == 0 else "$" if code in STOCK_MARKETS else ""
            )
            price = prefix + f"{display['price']:,.{asset.decimals}f}"
            change = f"{display['change']:+.2f}%" if display["change"] is not None else change
            if value.extended:
                change += " · 정규장 종가 대비"
            stamp = (value.extended.as_of if value.extended else value.as_of).astimezone(
                ZoneInfo("Asia/Seoul")
            )
            old = datetime.now(UTC) - value.as_of > timedelta(hours=2)
            prefix = "마지막 거래" if old else "공개 조회"
            phase = (
                {"regular": "정규장", "pre": "장전", "post": "장후"}[display["session"]]
                if code in STOCK_MARKETS
                else ""
            )
            if display["marketState"] == "closed":
                phase = "장 마감"
                prefix = (
                    "장후 마지막 거래가"
                    if value.extended and value.extended.session == "post"
                    else "장전 마지막 거래가"
                    if value.extended
                    else "마지막 거래가"
                )
            status = f"{phase} {prefix} · {stamp:%m.%d %H:%M} KST · 지연 " + (
                f"{value.delay_minutes}분" if value.delay_minutes is not None else "미확인"
            )
            if context.feed(asset.card_id.removeprefix("macro-")).error:
                status += " · 갱신 지연"
            direction = (
                "up"
                if display["change"] is not None and display["change"] >= 0
                else "down"
                if display["change"] is not None
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
    source = (
        f"{EXCHANGE_HISTORY[code].exchange} · {EXCHANGE_HISTORY[code].unit}" if session else "Binance · USDT"
    )
    classes = "board-detail" if detail else "board-asset" + (" btc-macro-card" if session else "")
    heading = f'<div class="board-identity">{asset_identity(code)}</div>'
    metrics = ""
    if not detail:
        if code in STOCK_MARKETS:

            def number(n):
                return f"{n:,.{asset.decimals}f}" if n is not None else "—"

            previous = (
                value.price / (1 + value.change)
                if value and value.change is not None and value.change > -1
                else None
            )
            metrics = (
                '<div class="board-metrics"><span>정규장 가격</span><b data-quote-field="regular">'
                + number(value.price if value else None)
                + "</b>"
                '<span>전일 종가</span><b data-quote-field="previous">' + number(previous) + "</b>"
                '<span>거래일 고가</span><b data-quote-field="high">'
                + number(value.day_high if value else None)
                + "</b>"
                '<span>거래일 저가</span><b data-quote-field="low">'
                + number(value.day_low if value else None)
                + "</b>"
                '<span>거래량</span><b data-quote-field="volume">'
                + (f"{value.volume:,.0f}주" if value and value.volume is not None else "—")
                + "</b></div>"
                '<div class="btc-macro-graph board-spark"></div>'
                '<span class="btc-macro-badge board-source">'
                + (
                    "장 마감"
                    if isinstance(value, MacroQuote) and quote_display(value)["marketState"] == "closed"
                    else "공개 조회"
                )
                + "</span>"
            )
        elif session:
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


@st.fragment(run_every=30)
def render_stock_references():
    from btc_analyzer.data.board_references import StockMood, WonRates

    context = current_context()
    with st.container(key="board_references"):
        for column, key, name in zip(
            st.columns(2, gap="small"), ("mood_us", "mood_kr"), ("미국 주식", "국내 주식")
        ):
            feed = context.feed(key)
            value = feed.value
            score = value.score if isinstance(value, StockMood) else None
            level = (
                "극단적 공포"
                if score is not None and score < 25
                else "공포"
                if score is not None and score < 45
                else "중립"
                if score is not None and score <= 55
                else "탐욕"
                if score is not None and score < 75
                else "극단적 탐욕"
            )
            stamp = (
                value.as_of.astimezone(ZoneInfo("Asia/Seoul")).strftime("%m.%d %H:%M KST")
                if isinstance(value, StockMood)
                else "자료 연결 대기"
            )
            with column:
                st.markdown(
                    f'<div class="board-sentiment"><span>{name} 공포·탐욕 · 자체 추정</span><b>{score if score is not None else "—"}</b><small>{level if score is not None else "산출 대기"} · {stamp}{" · 갱신 지연" if feed.error else ""}</small></div>',
                    unsafe_allow_html=True,
                )
        feed = context.feed("fx_extra")
        value = feed.value
        for column, name, amount in zip(
            st.columns(2, gap="small"),
            ("엔화 · 100 JPY", "유로화 · 1 EUR"),
            (getattr(value, "yen100", None), getattr(value, "euro", None)),
        ):
            price = f"₩{amount:,.2f}" if isinstance(value, WonRates) else "—"
            stamp = (
                f"{value.as_of:%m.%d} 기준 · ECB 일별" if isinstance(value, WonRates) else "자료 연결 대기"
            )
            with column:
                st.markdown(
                    f'<div class="board-fx"><span>{name}</span><b>{price}</b><small>{stamp}{" · 갱신 지연" if feed.error else ""}</small></div>',
                    unsafe_allow_html=True,
                )
    st.caption(
        "주식 공탐: S&P 500·코스피의 가격 위치·모멘텀·추세·변동성 기반 자체 추정(0 공포~100 탐욕). 공식 공탐지수가 아니며 표시 시각의 확정 일봉 기준입니다."
    )


def market_columns(codes):
    """Wrap added markets into another row instead of truncating the catalog."""
    values = list(codes)
    for start in range(0, len(values), 4):
        yield from zip(st.columns(4, gap="small"), values[start : start + 4])


def render_board(on_open):
    render_quote_snapshot()
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
    render_stock_references()
    st.markdown(
        '<div class="board-nav"><b>전체 시세</b><span>종목을 누르면 상세 차트가 열려요</span></div>',
        unsafe_allow_html=True,
    )
    section_heading("금 · 유가 · 국채 금리", len(MACRO_MARKETS), "국채는 채권 가격이 아닌 금리(%)")
    with st.container(key="board_sessions_macro"):
        render_session_cards(on_open, tuple(MACRO_MARKETS))
    for title, codes, subtitle in (
        (
            "국내 주식",
            tuple(code for code in STOCK_MARKETS if EXCHANGE_HISTORY[code].calendar == "KRX"),
            "KRX · 원화 · NXT 20시 거래 미제공",
        ),
        (
            "미국 주식",
            tuple(code for code in STOCK_MARKETS if EXCHANGE_HISTORY[code].calendar == "NYSE"),
            "NASDAQ · USD · 장전·장후 포함 · 야간 미제공",
        ),
    ):
        section_heading(title, len(codes), subtitle)
        with st.container(key="board_sessions_" + codes[0]):
            render_session_cards(on_open, codes)
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
    section_heading("지수 · 선물", len(INDEX_MARKETS), "거래소 운영 시간 · 공개 자료 지연 별도")
    with st.container(key="board_sessions"):
        render_session_cards(on_open, tuple(INDEX_MARKETS))
    st.markdown(
        '<p class="board-footnote">수신 시각과 지연 상태를 함께 확인하세요. 예측은 과거 자료·기술 지표에 기반한 시나리오예요.</p>',
        unsafe_allow_html=True,
    )


def render_session_cards(on_open, codes):
    context = current_context()
    for column, code in market_columns(codes):
        with column, st.container(key=f"board_card_{code}"):
            st.markdown(quote_fields(code, context=context), unsafe_allow_html=True)
            st.button(
                f"{MARKETS[code].name} 차트 열기",
                key=f"open_{code}",
                width="stretch",
                on_click=on_open,
                args=(code,),
            )
