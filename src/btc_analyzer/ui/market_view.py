"""Chart controls reuse closed-candle features without a separate strategy run."""

from btc_analyzer.assets import ASSETS, EXCHANGE_HISTORY

import streamlit as st
import pandas as pd

from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

from btc_analyzer.config import CHART_TIMEFRAMES, CHART_CANDLES
from btc_analyzer.candles import candle_close
from btc_analyzer.strategy.composite import FRAME_LABELS
from btc_analyzer.ui.charts import price_chart, READ_CHART_CONFIG, bind_asset
from btc_analyzer.ui.chart_reader import reader_html
from btc_analyzer.market_clock import bar_closes
from btc_analyzer.ui.canvas_chart import canvas_market


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def market_chart_spec(
    features,
    timezone,
    averages,
    bands,
    quote,
    ichimoku,
    detailed,
    bars,
    timeframe,
    displacement,
):
    features = features.copy(deep=False)
    features.attrs = {**features.attrs, "timeframe": timeframe, "ichimoku_displacement": displacement}
    fig = price_chart(
        features,
        None,
        timezone,
        averages,
        bands,
        quote=quote,
        ichimoku=ichimoku,
        ichimoku_detail=detailed,
        zones_visible=False,
        levels_visible=False,
        bars=bars,
        oscillators=True,
    )
    fig.update_layout(
        uirevision=f"market-{features.attrs.get('timeframe')}-{bars}",
        transition={"duration": 0},
        meta={
            "btcLive": {
                "kind": "market",
                "timeframe": timeframe,
                "timezone": timezone,
                "bars": bars,
                "label": FRAME_LABELS[timeframe],
                "closedEnd": int(bar_closes(features, features.index[-1], timeframe).timestamp() * 1000),
            }
        },
    )
    fig.update_xaxes(
        tickformat="%m.%d<br>%H:%M" if timeframe in ("5m", "15m", "1h", "4h") else "%y.%m.%d",
        nticks=5,
        row=4,
        col=1,
    )
    overlays = {}
    bands_seen = iter(("bb_upper", "bb_middle", "bb_lower"))
    for index, trace in enumerate(fig.data):
        if trace.name.startswith("EMA "):
            overlays[str(index)] = trace.name.lower().replace(" ", "_")
        elif trace.name in ("RSI", "MACD", "MACD 시그널", "MACD 히스토그램"):
            overlays[str(index)] = {
                "RSI": "rsi",
                "MACD": "macd",
                "MACD 시그널": "macd_signal",
                "MACD 히스토그램": "macd_hist",
            }[trace.name]
        elif trace.name in ("전환선", "기준선"):
            overlays[str(index)] = "ichimoku_tenkan" if trace.name == "전환선" else "ichimoku_kijun"
        elif trace.name == "볼린저 밴드":
            overlays[str(index)] = next(bands_seen)
    from btc_analyzer.ui.oscillator_chart import PANELS, macd_range

    fig.layout.meta["btcLive"]["overlays"] = overlays
    fig.layout.meta["btcLive"]["panels"] = PANELS
    fig.layout.meta["btcLive"]["volumeIndex"] = next(i for i, t in enumerate(fig.data) if t.name == "거래량")
    window = min(120, len(features), bars)
    fig.layout.meta["btcLive"]["window"] = window
    fig.layout.meta["btcLive"]["displacement"] = displacement
    shown = features.tail(bars)
    visible = shown.tail(window)
    low, high = float(visible.low.min()), float(visible.high.max())
    padding = max(high - low, high * 0.001) * 0.12
    fig.update_yaxes(range=[low - padding, high + padding], autorange=False, row=1, col=1)
    fig.update_yaxes(range=[0, max(float(visible.volume.max()), 1) * 1.12], autorange=False, row=2, col=1)
    fig.update_yaxes(range=macd_range(visible), autorange=False, row=4, col=1)
    step = (
        shown.index[-1] - shown.index[-2]
        if len(shown) > 1
        else candle_close(shown.index[-1], timeframe) - shown.index[-1]
    )
    left = shown.index[-window] - step * 0.7
    right = shown.index[-1] + step * 1.5
    fig.update_xaxes(range=[left.tz_convert(timezone), right.tz_convert(timezone)])
    fig.update_yaxes(side="right", title_text=None, row=1, col=1)
    fig.update_yaxes(side="right", title_text=None)
    fig.update_layout(
        height=640, margin={"t": 12, "b": 30, "l": 5, "r": 5}, showlegend=False, hovermode=False
    )
    # Plotly's date axes use display wall time. Integer milliseconds avoid
    # repeating long ISO/timezone strings in every overlay; source cutoffs stay UTC.
    for trace in fig.data:
        trace.x = [
            None if t is None else int(pd.Timestamp(t).tz_localize(None).value // 1_000_000) for t in trace.x
        ]
    fig.update_xaxes(type="date")
    return canvas_market(fig.to_dict())


def render_price_chart(
    features,
    timeframe,
    asset_code,
    *,
    timezone="Asia/Seoul",
    averages=("ema_20", "ema_50", "ema_200"),
    displacement=26,
):
    """One bounded chart/reader path for crypto, stocks, indices and commodities."""
    unit = EXCHANGE_HISTORY[asset_code].unit if asset_code in EXCHANGE_HISTORY else "USDT"
    shown = features.tail(CHART_CANDLES)
    st.markdown(
        reader_html(shown, timeframe, asset_code, tuple(averages), True).replace("USDT", unit),
        unsafe_allow_html=True,
    )
    spec = market_chart_spec(
        shown, timezone, tuple(averages), True, unit, True, True, len(shown), timeframe, displacement
    )
    st.plotly_chart(
        bind_asset(spec, asset_code), width="stretch", key="chart_01", theme=None, config=READ_CHART_CONFIG
    )
    st.caption(f"불러온 확정 봉 {len(shown):,}개 · 최대 {CHART_CANDLES:,}개 · 제공 이력 범위 내 표시")


@st.fragment
def render_market_chart(
    *,
    cfg,
    display_timezone,
    average_lines,
    asset_code="BTC",
    cache_path="data/web/market-cache.sqlite3",
):
    with st.container(key="chart_controls"):
        chart_tf = (
            st.segmented_control(
                "차트 시간대",
                CHART_TIMEFRAMES,
                default="1d",
                format_func=FRAME_LABELS.get,
                key="price_chart_timeframe",
                required=True,
                label_visibility="collapsed",
            )
            or "1d"
        )
    from btc_analyzer.ui.chart_data import selected_chart_history
    from btc_analyzer.data.base_provider import DataError

    try:
        features = selected_chart_history(cache_path, ASSETS[asset_code].symbol, chart_tf, cfg.indicators)
    except DataError as exc:
        st.info(f"{FRAME_LABELS[chart_tf]} 연결 대기 · {exc}")
        return
    from btc_analyzer.ui.live_analysis import render_chart_seed

    render_chart_seed(features, chart_tf, cfg.indicators, ASSETS[asset_code].stream_symbol)
    render_price_chart(
        features,
        chart_tf,
        asset_code,
        timezone=display_timezone,
        averages=average_lines,
        displacement=cfg.indicators.ichimoku_displacement,
    )
    st.caption(
        "드래그로 이동 · 두 손가락으로 봉 수 조절 · 길게 눌러 가격 · 오토는 보이는 봉의 가격축에 맞춰요."
    )
    st.caption(
        f"{FRAME_LABELS[chart_tf]} · Binance {ASSETS[asset_code].symbol} · EMA·볼린저·일목·RSI·MACD 항상 표시 · 진행 중 봉은 잠정값이에요."
    )
