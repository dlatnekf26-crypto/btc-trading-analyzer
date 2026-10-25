"""On-demand market detail. Keep collection and analysis off the quote board."""

import logging
import os
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st
from btc_analyzer.assets import MARKETS, SESSION_MARKETS
from btc_analyzer.candles import candle_boundary
from btc_analyzer.config import AppConfig
from btc_analyzer.data.base_provider import DataError
from btc_analyzer.ui.analysis_cache import market_snapshot
from btc_analyzer.ui.presentation import decision_panel
from btc_analyzer.ui.market_context import render_coin_news

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


@st.cache_data(ttl=60, max_entries=12, show_spinner=False)
def get_live_bundle(cache: str, market: str, pair: str, tf: str, start, end, _refresh=False) -> dict:
    from btc_analyzer.data.service import DataService

    return DataService(cache).bundle(market, pair, tf, start, end, include_macro=True, refresh=_refresh)


@st.fragment(run_every=60)
def dashboard(asset_code: str) -> None:
    cache_path = Path(os.getenv("BTC_WEB_DATA_DIR", "data/web")) / "market-cache.sqlite3"
    asset = MARKETS[asset_code]
    symbol = asset.symbol
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
        st.info("시세 카드의 실시간 연결은 독립적으로 유지됩니다. 분석은 데이터를 받은 뒤 표시합니다.")
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
                cfg=cfg,
                display_timezone=display_timezone,
                average_lines=average_lines,
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


def render_market_analysis(asset_code):
    if asset_code in SESSION_MARKETS:
        from btc_analyzer.ui.exchange_view import render_exchange_market

        render_exchange_market(asset_code)
    else:
        dashboard(asset_code)
    from btc_analyzer.ui.ai_view import settings as ai_settings, render_ai_panel

    if ai_settings()[0]:
        render_ai_panel()
    # News remains an independent fragment and keeps the live alert bridge current
    # on every tab, without pushing the price/forecast chart below a long news feed.
    if asset_code not in SESSION_MARKETS:
        render_coin_news(asset_code)
