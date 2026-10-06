"""A small BTC dashboard: markets, indicators, multi-frame signals and forecasts."""
# ruff: noqa: E402 -- prepare the checkout before project imports.

import logging
import os
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path[:] = [str(PROJECT_ROOT), *[path for path in sys.path if path != str(PROJECT_ROOT)]]
from checkout_bootstrap import ensure_checkout

SOURCE_VERSION = globals().get("CHECKOUT_SOURCE_VERSION") or ensure_checkout(PROJECT_ROOT)

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from btc_analyzer.config import AppConfig
from btc_analyzer.candles import candle_boundary
from btc_analyzer.data.service import DataService
from btc_analyzer.data.base_provider import DataError
from btc_analyzer.strategy.composite import FRAME_LABELS, FRAME_WEIGHTS
from btc_analyzer.ui.analysis_cache import market_snapshot
from btc_analyzer.ui.presentation import BRAND, CSS, LABELS, korean, composite_cards, decision_panel
from btc_analyzer.ui.live_prices import render_live_prices
from btc_analyzer.ui.market_context import render_market_context

load_dotenv(override=False)
logging.basicConfig(level=os.getenv("BTC_LOG_LEVEL", "INFO"))
st.set_page_config(page_title="BTC Signal Lab · 실시간 시장 분석", page_icon="₿", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(BRAND, unsafe_allow_html=True)
cache_path = Path(os.getenv("BTC_WEB_DATA_DIR", "data/web")) / "market-cache.sqlite3"
cfg = AppConfig()
display_timezone = "Asia/Seoul"
exchange, symbol, quote_currency, timeframe = "Binance", "BTC/USDT", "USDT", "1d"
average_lines = ("ema_20", "ema_50", "ema_200")


def request_market_refresh() -> None:
    st.session_state["market_refresh_sequence"] = st.session_state.get("market_refresh_sequence", 0) + 1


def open_history_comparison() -> None:
    st.session_state["dashboard_tab"] = "미래 예측"
    st.session_state["similarity_timeframe"] = st.session_state.get("price_chart_timeframe", "1d")
    st.session_state["forecast_horizon"] = (
        "1mo" if st.session_state["similarity_timeframe"] == "1d" else "custom"
    )


with st.container(key="market_controls"):
    market_control, refresh_control = st.columns([5, 2], vertical_alignment="bottom")
    with market_control:
        st.caption("Binance · BTC/USDT · LIVE")
    with refresh_control:
        st.button("데이터 새로고침", on_click=request_market_refresh, width="stretch")
# Render before any server-side candle request. Quote ticks never rerun Python.
render_live_prices()
render_market_context()
st.caption(f"분석 기준 {exchange} {symbol} · 확정 봉으로 계산 · 실시간 현재가와 구분해요.")


@st.cache_data(ttl=60, max_entries=12, show_spinner=False)
def get_live_bundle(cache: str, market: str, pair: str, tf: str, start, end, _refresh=False) -> dict:
    return DataService(cache).bundle(market, pair, tf, start, end, include_macro=True, refresh=_refresh)


@st.fragment(run_every=60)
def dashboard() -> None:
    sequence = st.session_state.get("market_refresh_sequence", 0)
    refresh = sequence != st.session_state.get("market_refresh_consumed", 0)
    st.session_state["market_refresh_consumed"] = sequence
    try:
        available_cutoff = pd.Timestamp.now(tz="UTC")
        collection_end = candle_boundary(available_cutoff, "1h")
        start = collection_end.normalize() - pd.Timedelta(days=30)
        args = (str(cache_path), exchange, symbol, timeframe, start, collection_end)
        with st.spinner("확정 봉을 불러오는 중…"):
            if refresh:
                get_live_bundle.clear(*args)
            bundle = get_live_bundle(*args, _refresh=refresh)
        if not any(not frame.empty for frame in bundle.values()):
            raise DataError("확정 봉을 받지 못했습니다.")
        cutoff = candle_boundary(available_cutoff, "1h")
        enriched, combined = market_snapshot(bundle, cutoff, cfg)
    except (DataError, ValueError, OSError, KeyError, sqlite3.Error) as exc:
        logging.exception("Market analysis failed")
        st.error(f"분석 데이터를 불러올 수 없습니다: {exc}")
        st.info("상단 실시간 시세 연결은 독립적으로 유지됩니다. 분석은 데이터를 받은 뒤 표시합니다.")
        return

    if st.session_state.get("dashboard_tab") not in (
        None,
        "시장 개요",
        "기술 지표",
        "다중 시간대",
        "미래 예측",
    ):
        st.session_state["dashboard_tab"] = "시장 개요"
    prediction_active = st.session_state.get("dashboard_tab") == "미래 예측"
    with (
        st.expander("현재 시장 · 종합 매수·매도 판단", expanded=False)
        if prediction_active
        else st.container()
    ):
        st.markdown(decision_panel(combined), unsafe_allow_html=True)
        st.markdown(composite_cards(combined), unsafe_allow_html=True)
        st.caption(
            f"수주~수개월 관점 · 마지막 확정 {pd.Timestamp(combined.timestamp).tz_convert(display_timezone):%m.%d %H:%M} KST"
        )
        if not prediction_active:
            st.button("미래 예측 보기 →", type="primary", on_click=open_history_comparison)
    tabs = st.tabs(
        ["시장 개요", "기술 지표", "다중 시간대", "미래 예측"],
        key="dashboard_tab",
        on_change="rerun",
    )
    if tabs[0].open:
        with tabs[0]:
            from btc_analyzer.ui.market_view import render_market_chart

            render_market_chart(
                bundle=bundle,
                enriched=enriched,
                cfg=cfg,
                display_timezone=display_timezone,
                average_lines=average_lines,
                quote_currency=quote_currency,
            )
            from btc_analyzer.ui.session_patterns import render_session_patterns

            render_session_patterns(bundle.get("1h"), cutoff)
            with st.expander("종합 판단의 전체 근거"):
                for reason in combined.reasons:
                    st.write(f"• {reason}")
            st.button("예측과 과거 차트 함께 보기", on_click=open_history_comparison)
    if tabs[1].open:
        with tabs[1]:
            from btc_analyzer.ui.indicators_view import render_indicators

            render_indicators(enriched, cfg.indicators, display_timezone)
    if tabs[2].open:
        with tabs[2]:
            st.subheader("다섯 시간대 통합 분석")
            rows = [
                {
                    "시간대": FRAME_LABELS[tf],
                    "상승 우위": round(frame.score, 1) if frame.ready else None,
                    "반영 비중": f"{FRAME_WEIGHTS[tf]:.0%}",
                    "연속 확정 봉": frame.bars,
                    "지표 충족": f"{frame.coverage:.0%}",
                    "상태": "반영" if frame.ready else "대기 / 미반영",
                    "시장 흐름": korean(frame.regime),
                    "변동성": korean(frame.volatility),
                    "확정 시각": str(pd.Timestamp(frame.confirmed_at).tz_convert(display_timezone))
                    if frame.confirmed_at
                    else "없음",
                }
                for tf, frame in combined.frames.items()
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.subheader("시간대별 전체 지표")
            indicator_rows = [
                {"시간대": FRAME_LABELS[tf], **frame.indicators} for tf, frame in combined.frames.items()
            ]
            st.dataframe(
                pd.DataFrame(indicator_rows).set_index("시간대").T.rename(index=LABELS),
                width="stretch",
            )
            st.caption(
                "빈칸은 이력이 부족해 계산할 수 없는 지표입니다. 월봉 EMA200·SMA200 등은 임의로 채우지 않습니다."
            )
            st.subheader("시간대별 지표 그룹 점수")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시간대": FRAME_LABELS[tf],
                            **{
                                korean(k): round(v, 1) if frame.ready else None
                                for k, v in frame.categories.items()
                            },
                        }
                        for tf, frame in combined.frames.items()
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            for tf, frame in combined.frames.items():
                if frame.notes:
                    with st.expander(f"{FRAME_LABELS[tf]} · 데이터 상태"):
                        for note in frame.notes:
                            st.write(note)
            st.caption(
                "주봉은 월요일 UTC 00:00, 월봉은 다음 달 1일 UTC 00:00에 확정됩니다. 미완성 봉은 제외합니다."
            )
            with st.expander("종합 신호 조건"):
                st.write(
                    "수주~수개월 관점: 1시간 5% · 4시간 10% · 일봉 40% · 주봉 30% · 월봉 15%. 단기 봉 상승은 매수의 필수 조건이 아니에요."
                )
                st.write(
                    "눌림목 매수: 중기 기준 대비 할인·고점 대비 조정·지지 접근과 하락 압력 둔화를 확인하고, 주봉·월봉 방향 및 일봉 비용 후 RR이 지지하면 분할매수를 검토해요."
                )
                st.write(
                    "매도: 일봉·주봉 하락이 함께 확인되면 현물 보유분 축소, 일봉 RSI와 가격 이격이 과열되면 분할 이익 실현 신호를 표시해요. 신규 숏 주문은 만들지 않아요."
                )
                st.write(
                    "급락·지지 이탈·거래량 부족은 신규 매수를 보류해요. 다섯 시간대의 핵심 지표가 부족하면 판단을 보류해요. 가격 매력은 기술적 상대 위치이며 적정 가치나 수익 확률이 아니에요."
                )
    if tabs[3].open:
        with tabs[3]:
            from btc_analyzer.ui.history_view import render_history_view

            render_history_view(
                cache_path=str(cache_path),
                exchange=exchange,
                symbol=symbol,
                cutoff=available_cutoff,
                demo=False,
                demo_frames={},
                research_timeframe=timeframe,
                timezone=display_timezone,
                refresh=refresh,
            )


dashboard()
