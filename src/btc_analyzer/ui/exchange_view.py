"""Shared chart/analysis/forecast for exchange markets; fetch only the viewed frame."""

import pandas as pd
import requests
import streamlit as st

from btc_analyzer.config import AppConfig, CHART_TIMEFRAMES
from btc_analyzer.assets import SESSION_MARKETS, EXCHANGE_HISTORY
from btc_analyzer.data.exchange_history import fetch_history, aggregate
from btc_analyzer.indicators.core import indicators
from btc_analyzer.market_clock import bar_closes
from btc_analyzer.strategy.composite import FRAME_LABELS
from btc_analyzer.ui.chart_reader import reader_html
from btc_analyzer.ui.charts import bind_asset, READ_CHART_CONFIG
from btc_analyzer.ui.market_view import market_chart_spec
from btc_analyzer.ui.history_view import render_history_view
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS


@st.cache_data(ttl=60, max_entries=24, show_spinner=False)
def market_response(market, timeframe, refresh_sequence=0):
    try:
        now = pd.Timestamp.now(tz="UTC")
        if timeframe in ("4h", "1w", "1M"):
            response = market_response(market, "1h" if timeframe == "4h" else "1d", refresh_sequence)
            if "error" in response:
                return response
            frame = aggregate(response["frame"], timeframe, now)
        else:
            frame = fetch_history(timeframe, now, market)
        if frame.empty:
            raise ValueError("확정 거래 봉이 없습니다.")
        return {"frame": frame}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return {"error": str(exc)}


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def market_features(frame, timeframe):
    return indicators(frame, timeframe=timeframe)


@st.fragment(run_every=60)
def render_exchange_market(market):
    asset, venue = SESSION_MARKETS[market], EXCHANGE_HISTORY[market]

    def frame(timeframe):
        response = market_response(market, timeframe, st.session_state.get("market_refresh_sequence", 0))
        if "error" in response:
            raise ValueError(response["error"])
        return response["frame"]

    if st.session_state.get("dashboard_tab") not in (None, "시장 개요", "미래 예측"):
        st.session_state["dashboard_tab"] = "시장 개요"
    tabs = st.tabs(["시장 개요", "미래 예측"], key="dashboard_tab", on_change="rerun")
    st.caption(
        f"{asset.symbol} · {venue.source} · 공개 지연 자료 · 1분마다 확정 봉 확인"
        + (" · 롤오버 가격 차이 포함" if market == "NQ" else f" · {venue.unit}")
        + (
            " · 현재가는 장외 포함, 차트·분석은 정규장 기준"
            if venue.kind == "EQUITY" and venue.calendar == "NYSE"
            else ""
        )
    )
    try:
        if tabs[0].open:
            with tabs[0]:
                tf = (
                    st.segmented_control(
                        "차트 시간대",
                        CHART_TIMEFRAMES,
                        default="1d",
                        required=True,
                        format_func=FRAME_LABELS.get,
                        key="price_chart_timeframe",
                        label_visibility="collapsed",
                    )
                    or "1d"
                )
                raw = frame(tf)
                features = market_features(raw, tf)
                if venue.calendar == "KRX" and tf in ("5m", "15m", "1h", "4h"):
                    st.caption(
                        "공개 분봉은 장 막판 자료가 빠질 수 있어요. 누락 시 지표를 다시 계산하며, 충분한 이력이 없으면 표시를 보류해요. 중장기 분석은 일봉을 권해요."
                    )
                st.markdown(
                    reader_html(features, tf, market, ("ema_20", "ema_50", "ema_200"), True).replace(
                        "USDT", venue.unit
                    ),
                    unsafe_allow_html=True,
                )
                spec = market_chart_spec(
                    features.tail(600),
                    "Asia/Seoul",
                    ("ema_20", "ema_50", "ema_200"),
                    True,
                    venue.unit,
                    True,
                    True,
                    min(600, len(features)),
                    tf,
                    AppConfig().indicators.ichimoku_displacement,
                )
                st.plotly_chart(
                    bind_asset(spec, market),
                    width="stretch",
                    theme=None,
                    config=READ_CHART_CONFIG,
                    key="chart_01",
                )
                close_at = bar_closes(raw, raw.index[-1], tf)
                row = features.iloc[-1]
                ready = pd.notna(row.ema_50) and pd.notna(row.rsi)
                trend = (
                    "상승 추세 우위"
                    if ready and row.close > row.ema_20 > row.ema_50
                    else "하락 추세 우위"
                    if ready and row.close < row.ema_20 < row.ema_50
                    else "방향 확인 중"
                )
                st.markdown(f"**{FRAME_LABELS[tf]} · {trend}**")
                st.caption(
                    f"확정 {close_at.tz_convert('Asia/Seoul'):%m.%d %H:%M} KST · RSI {row.rsi:.1f} · EMA20 대비 {(row.close / row.ema_20 - 1):+.1%}"
                    if ready
                    else "지표에 필요한 연속 이력이 부족합니다."
                )
                st.caption(
                    "드래그 이동 · 휠/시간축 드래그로 봉 수 조절 · 가격축 드래그로 높이 조절 · 두 손가락 확대·축소 · 오토 가격축. "
                    + (
                        "일봉은 미국 정규 거래일 기준(단축장 제외), 주·월봉은 이 일봉을 합산해요."
                        if market == "NQ"
                        else "한국 거래일·거래시간 기준. 주·월봉은 확정 일봉을 합산해요."
                        if venue.calendar == "KRX"
                        else "미국 정규장·단축장 기준. 주·월봉은 확정 일봉을 합산해요."
                    )
                    + " 휴장일은 가짜 봉으로 채우지 않아요."
                )
        if tabs[1].open:
            with tabs[1]:
                render_history_view(
                    cache_path="",
                    exchange=venue.exchange,
                    symbol=asset.symbol,
                    cutoff=pd.Timestamp.now(tz="UTC"),
                    demo=False,
                    demo_frames={},
                    timezone="Asia/Seoul",
                    market_frames=frame,
                )
    except (ValueError, KeyError) as exc:
        st.info(f"{asset.name} 분석 대기 · {exc}")
