"""Fetch bounded chart history only when selected; reuse incremental disk history."""

import sqlite3

import pandas as pd
import streamlit as st

from btc_analyzer.candles import candle_boundary
from btc_analyzer.config import CHART_CANDLES, CHART_WARMUP
from btc_analyzer.data.base_provider import DataError
from btc_analyzer.data.service import DataService
from btc_analyzer.indicators.core import indicators
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS


@st.cache_data(ttl=60, max_entries=16, show_spinner=False)
def chart_history(cache_path, symbol, timeframe, boundary, _refresh=False):
    try:
        return {
            "frame": DataService(cache_path).history(
                "Binance", symbol, timeframe, boundary, CHART_CANDLES + CHART_WARMUP, refresh=_refresh
            )
        }
    except (DataError, ValueError, OSError, sqlite3.Error) as exc:
        return {"error": str(exc)}


@st.cache_data(ttl=3600, max_entries=16, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def chart_features(frame, timeframe, cfg):
    return indicators(frame, cfg, timeframe)


def selected_chart_history(cache_path, symbol, timeframe, cfg):
    boundary = candle_boundary(pd.Timestamp.now(tz="UTC"), timeframe).isoformat()
    args = (cache_path, symbol, timeframe, boundary)
    sequence = st.session_state.get("market_refresh_sequence", 0)
    key = f"chart_refresh_{symbol}_{timeframe}"
    force = sequence > st.session_state.get(key, 0)
    if force:
        chart_history.clear(*args)
    st.session_state[key] = sequence
    result = chart_history(*args, _refresh=force)
    if "error" in result:
        raise DataError(result["error"])
    if result["frame"].empty:
        raise DataError("확정 차트 봉을 받지 못했습니다.")
    return chart_features(result["frame"], timeframe, cfg)
