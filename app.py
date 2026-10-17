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
from btc_analyzer.assets import MARKETS
from btc_analyzer.candles import candle_boundary
from btc_analyzer.data.service import DataService
from btc_analyzer.data.base_provider import DataError
from btc_analyzer.ui.analysis_cache import market_snapshot
from btc_analyzer.ui.presentation import BRAND, CSS, decision_panel
from btc_analyzer.ui.live_prices import render_live_prices
from btc_analyzer.ui.market_context import render_macro_quotes, render_coin_news
from btc_analyzer.ui.pwa import INSTALL_CONTROL

load_dotenv(override=False)
logging.basicConfig(level=os.getenv("BTC_LOG_LEVEL", "INFO"))
st.set_page_config(page_title="Crypto Signal Lab · 실시간 시장 분석", page_icon="◈", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(
    BRAND.replace('<span class="btc-brand-tag">가격 · 흐름 · 근거</span>', INSTALL_CONTROL),
    unsafe_allow_html=True,
)
cache_path = Path(os.getenv("BTC_WEB_DATA_DIR", "data/web")) / "market-cache.sqlite3"
cfg = AppConfig()
display_timezone = "Asia/Seoul"
exchange, quote_currency, timeframe = "Binance", "USDT", "1d"
average_lines = ("ema_20", "ema_50", "ema_200")


def request_market_refresh() -> None:
    st.session_state["market_refresh_sequence"] = st.session_state.get("market_refresh_sequence", 0) + 1


def open_history_comparison() -> None:
    st.session_state["dashboard_tab"] = "미래 예측"
    selected = st.session_state.get("price_chart_timeframe", "1d")
    st.session_state["similarity_timeframe"] = selected if selected not in ("5m", "15m") else "1d"
    st.session_state["forecast_horizon"] = (
        "1mo" if st.session_state["similarity_timeframe"] == "1d" else "custom"
    )


with st.container(key="market_controls"):
    market_control, refresh_control = st.columns([3, 1], vertical_alignment="bottom")
    with market_control:
        asset_code = (
            st.segmented_control(
                "분석할 시장",
                list(MARKETS),
                default="BTC",
                required=True,
                key="analysis_asset",
                label_visibility="collapsed",
            )
            or "BTC"
        )
    with refresh_control:
        st.button("새로고침", on_click=request_market_refresh, width="stretch")
asset = MARKETS[asset_code]
symbol = asset.symbol
# Render before any server-side candle request. Quote ticks never rerun Python.
render_live_prices(asset_code)


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

    from btc_analyzer.ui.live_analysis import render_live_analysis

    if st.session_state.get("dashboard_tab") not in (None, "시장 개요", "미래 예측"):
        st.session_state["dashboard_tab"] = "시장 개요"
    prediction_active = st.session_state.get("dashboard_tab") == "미래 예측"

    def render_current_analysis():
        with st.expander("종합 판단 · 매수·매도와 가격 근거", expanded=False):
            render_live_analysis(enriched, cfg.indicators, asset.stream_symbol)
            st.markdown(decision_panel(combined), unsafe_allow_html=True)
            st.caption(
                f"수주~수개월 관점 · 마지막 확정 {pd.Timestamp(combined.timestamp).tz_convert(display_timezone):%m.%d %H:%M} KST"
            )
            if not prediction_active:
                st.button("미래 예측 보기 →", type="primary", on_click=open_history_comparison)

    tabs = st.tabs(
        ["시장 개요", "미래 예측"],
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
                asset_code=asset_code,
                cache_path=str(cache_path),
            )
            render_current_analysis()
            from btc_analyzer.ui.market_insights import render_market_insights

            render_market_insights(bundle.get("1M"), cutoff, asset_code)
            with st.expander("종합 판단의 전체 근거"):
                for reason in combined.reasons:
                    st.write(f"• {reason}")
    if tabs[1].open:
        with tabs[1]:
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

    if not tabs[0].open:
        render_current_analysis()


if asset_code == "NQ":
    from btc_analyzer.ui.nasdaq_view import render_nasdaq

    with st.container(key="selected_future"):
        render_macro_quotes(("nq",))
    render_nasdaq()
else:
    dashboard()
from btc_analyzer.ui.ai_view import settings as ai_settings, render_ai_panel

if ai_settings()[0]:
    render_ai_panel()
with st.expander("대외 시장 · 나스닥·유가·국채", expanded=False):
    render_macro_quotes(("oil", "tnx", "tyx") if asset_code == "NQ" else ("nq", "oil", "tnx", "tyx"))
# News remains an independent fragment and keeps the live alert bridge current
# on every tab, without pushing the price/forecast chart below a long news feed.
if asset_code != "NQ":
    render_coin_news(asset_code)
