"""A small BTC dashboard: markets, indicators, multi-frame signals and forecasts."""
# ruff: noqa: E402 -- prepare the checkout before project imports.

import logging
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path[:] = [str(PROJECT_ROOT), *[path for path in sys.path if path != str(PROJECT_ROOT)]]
from checkout_bootstrap import ensure_checkout

SOURCE_VERSION = globals().get("CHECKOUT_SOURCE_VERSION") or ensure_checkout(PROJECT_ROOT)

import streamlit as st
from dotenv import load_dotenv

from btc_analyzer.assets import MARKETS
from btc_analyzer.ui.presentation import BRAND, CSS
from btc_analyzer.ui.live_prices import render_live_prices
from btc_analyzer.ui.market_board import render_board, detail_heading, BOARD_CSS
from btc_analyzer.ui.pwa import INSTALL_CONTROL

load_dotenv(override=False)
logging.basicConfig(level=os.getenv("BTC_LOG_LEVEL", "INFO"))
st.set_page_config(page_title="Crypto Signal Lab · 실시간 시장 분석", page_icon="◈", layout="wide")
st.html(CSS + BOARD_CSS)
st.markdown(
    BRAND.replace('<span class="btc-brand-tag">가격 · 흐름 · 근거</span>', INSTALL_CONTROL),
    unsafe_allow_html=True,
)

# A public link and browser history use the same route as the market cards.
route = (st.query_params.get("market"), st.query_params.get("view"))
if route != st.session_state.get("market_route_seen"):
    code, view = route
    st.session_state["analysis_asset"] = code if code in MARKETS else "BTC"
    st.session_state["market_detail_open"] = code in MARKETS and view == "chart"


def open_market(code):
    st.session_state["analysis_asset"] = code
    st.session_state["market_detail_open"] = True
    st.query_params.update({"market": code, "view": "chart"})


def close_market():
    st.session_state["market_detail_open"] = False
    for key in ("market", "view"):
        if key in st.query_params:
            del st.query_params[key]


@st.dialog("차트 · 분석", width="large", on_dismiss=close_market)
def market_detail(code):
    from btc_analyzer.ui.analysis_view import render_market_analysis, request_market_refresh

    st.markdown(detail_heading(code), unsafe_allow_html=True)
    with st.container(key="market_controls"):
        market_control, refresh_control = st.columns([3, 1], vertical_alignment="bottom")
        with market_control:
            selected = (
                st.segmented_control(
                    "분석할 시장",
                    list(MARKETS),
                    required=True,
                    format_func=lambda value: "코스피" if value == "KOSPI" else value,
                    key="analysis_asset",
                    label_visibility="collapsed",
                )
                or "BTC"
            )
        with refresh_control:
            st.button("새로고침", on_click=request_market_refresh, width="stretch")
    if selected != code:
        st.query_params.update({"market": selected, "view": "chart"})
        st.rerun(scope="app")
    render_market_analysis(code)


if st.session_state.get("market_detail_open"):
    st.query_params.update({"market": st.session_state.get("analysis_asset", "BTC"), "view": "chart"})

st.session_state["market_route_seen"] = (st.query_params.get("market"), st.query_params.get("view"))

# One persistent browser bridge owns every quote and the chart gestures.
with st.container(key="quote_bridge"):
    render_live_prices(st.session_state.get("analysis_asset", "BTC"))
render_board(open_market)
if st.session_state.get("market_detail_open"):
    market_detail(st.session_state.get("analysis_asset", "BTC"))
