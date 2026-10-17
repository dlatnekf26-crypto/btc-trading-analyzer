"""Small, exact indicator seeds and a browser-owned provisional candle layer."""

from html import escape
import json

import numpy as np
from btc_analyzer.ui.browser_assets import browser_asset, live_analysis_js


import streamlit as st

from btc_analyzer.candles import candle_close
from btc_analyzer.config import COMPOSITE_TIMEFRAMES
from btc_analyzer.indicators.core import wilder
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def live_seed_json(enriched, cfg):
    """Continue recursive indicators from the entire last contiguous segment.

    Only 80 rolling OHLCV samples are sent. Recursive EMA/Wilder states retain
    their full history, avoiding the bias of recalculating from a short tail.
    The caller supplies already closed, gap-aware feature frames.
    """
    frames = {}
    for tf in COMPOSITE_TIMEFRAMES:
        frame = enriched.get(tf)
        if frame is None or frame.empty:
            continue
        count = int(frame.bars_since_gap.iloc[-1])
        segment = frame.tail(count)
        close = segment.close
        delta = close.diff()
        row = frame.iloc[-1]

        def number(value):
            return float(value) if np.isfinite(value) else None

        ema = {
            str(n): number(close.ewm(span=n, adjust=False).mean().iloc[-1])
            for n in set((*cfg.ema_lengths, cfg.macd_fast, cfg.macd_slow))
        }
        line = close.ewm(span=cfg.macd_fast, adjust=False, min_periods=cfg.macd_fast).mean() - (
            close.ewm(span=cfg.macd_slow, adjust=False, min_periods=cfg.macd_slow).mean()
        )
        frames[tf] = {
            "at": int(frame.index[-1].timestamp() * 1000),
            "end": int(candle_close(frame.index[-1], tf).timestamp() * 1000),
            "count": count,
            "ema": ema,
            "gain": number(wilder(delta.clip(lower=0), cfg.rsi_length).iloc[-1]),
            "loss": number(wilder(-delta.clip(upper=0), cfg.rsi_length).iloc[-1]),
            "signal": number(line.ewm(span=cfg.macd_signal, adjust=False).mean().iloc[-1]),
            "atr": number(row.atr),
            "rows": [
                [int(t.timestamp() * 1000), *map(float, values)]
                for t, values in segment[["open", "high", "low", "close", "volume"]].tail(80).iterrows()
            ],
        }
    parameters = {
        key: getattr(cfg, key)
        for key in (
            "rsi_length",
            "atr_length",
            "bb_length",
            "bb_std",
            "macd_fast",
            "macd_slow",
            "macd_signal",
            "ichimoku_conversion",
            "ichimoku_base",
            "ichimoku_span_b",
            "ichimoku_displacement",
        )
    }
    return json.dumps({"frames": frames, "cfg": parameters}, separators=(",", ":"), allow_nan=False)


def render_live_analysis(enriched, cfg, symbol="BTCUSDT"):
    seeds = {
        tf: frame[["open", "high", "low", "close", "volume", "bars_since_gap", "atr"]]
        for tf, frame in enriched.items()
        if tf in COMPOSITE_TIMEFRAMES and not frame.empty
    }
    payload = escape(live_seed_json(seeds, cfg), quote=True)
    st.markdown(
        f'<section id="btc-live-analysis" data-symbol="{escape(symbol, quote=True)}" data-seeds="{payload}" aria-label="실시간 잠정 분석">'
        '<div class="btc-live-heading"><strong>지금, 다섯 시간대</strong>'
        '<span class="btc-live-status">진행 중 봉 연결 대기</span></div>'
        '<div class="btc-live-frames">'
        + "".join(
            f'<article data-tf="{tf}"><b>{label}</b><strong>—</strong><span>봉 수신 대기</span>'
            '<span class="btc-live-volatility"></span></article>'
            for tf, label in zip(COMPOSITE_TIMEFRAMES, ("1시간", "4시간", "일봉", "주봉", "월봉"))
        )
        + '</div><p class="btc-live-note">진행 중 봉의 EMA·RSI·MACD·변동성·일목을 갱신해요. '
        "봉 마감 전 값은 바뀌며, 종합 매수·매도와 과거 검증은 확정 봉 기준이에요.</p></section>",
        unsafe_allow_html=True,
    )


LIVE_ANALYSIS_CSS = "<style>" + browser_asset("live-analysis.css") + "</style>"


LIVE_ANALYSIS_JS = live_analysis_js()
