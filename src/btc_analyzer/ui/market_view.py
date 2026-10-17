"""Chart controls reuse closed-candle features without a separate strategy run."""

from html import escape
from btc_analyzer.assets import ASSETS, price_text

import streamlit as st
import pandas as pd

from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

from btc_analyzer.config import COMPOSITE_TIMEFRAMES
from btc_analyzer.candles import candle_close
from btc_analyzer.strategy.composite import FRAME_LABELS
from btc_analyzer.ui.charts import price_chart, READ_CHART_CONFIG, bind_asset
from btc_analyzer.ui.chart_reader import reader_html


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
                "closedEnd": int(candle_close(features.index[-1], timeframe).timestamp() * 1000),
            }
        },
    )
    fig.update_xaxes(
        tickformat="%m.%d<br>%H:%M" if timeframe in ("1h", "4h") else "%y.%m.%d", nticks=5, row=2, col=1
    )
    overlays = {}
    bands_seen = iter(("bb_upper", "bb_middle", "bb_lower"))
    for index, trace in enumerate(fig.data):
        if trace.name.startswith("EMA "):
            overlays[str(index)] = trace.name.lower().replace(" ", "_")
        elif trace.name == "볼린저 밴드":
            overlays[str(index)] = next(bands_seen)
    fig.layout.meta["btcLive"]["overlays"] = overlays
    window = min(60, len(features), bars)
    fig.layout.meta["btcLive"]["window"] = window
    shown = features.tail(bars)
    step = (
        shown.index[-1] - shown.index[-2]
        if len(shown) > 1
        else candle_close(shown.index[-1], timeframe) - shown.index[-1]
    )
    left = shown.index[-window] - step * 0.7
    right = shown.index[-1] + step * 1.5
    fig.update_xaxes(range=[left.tz_convert(timezone), right.tz_convert(timezone)])
    fig.update_yaxes(side="right", title_text=None, row=1, col=1)
    fig.update_yaxes(side="right", row=2, col=1)
    fig.update_layout(height=470, margin={"t": 30, "b": 30, "l": 5, "r": 5}, legend={"y": 1.01})
    # Plotly's date axes use display wall time. Integer milliseconds avoid
    # repeating long ISO/timezone strings in every overlay; source cutoffs stay UTC.
    for trace in fig.data:
        trace.x = [int(pd.Timestamp(t).tz_localize(None).value // 1_000_000) for t in trace.x]
    fig.update_xaxes(type="date")
    return fig.to_dict()


@st.fragment
def render_market_chart(
    *, bundle, enriched, cfg, display_timezone, average_lines, quote_currency, asset_code="BTC"
):
    with st.container(key="chart_controls"):
        frames, options = st.columns([4, 1], vertical_alignment="bottom")
        with frames:
            chart_tf = (
                st.segmented_control(
                    "차트 시간대",
                    COMPOSITE_TIMEFRAMES,
                    default="1d",
                    format_func=FRAME_LABELS.get,
                    key="price_chart_timeframe",
                    required=True,
                    label_visibility="collapsed",
                )
                or "1d"
            )
        with options, st.popover("지표"):
            chart_view = (
                st.segmented_control("차트 보기", ["간편", "상세"], default="간편", required=True) or "간편"
            )
            overlays = st.pills(
                "겹쳐 볼 지표",
                ["이동평균선", "볼린저밴드", "일목균형표"],
                selection_mode="multi",
                default=["이동평균선", "볼린저밴드"],
            )
            detailed_chart = chart_view == "상세"
            chart_bars = 120
            if detailed_chart:
                chart_bars = st.select_slider("표시할 봉 수", options=[60, 120, 240, 400], value=240)
    chart_raw = bundle.get(chart_tf)
    if chart_raw is not None and not chart_raw.empty:
        chart_features = enriched[chart_tf]
        visible = chart_features.tail(chart_bars)
        first_price, last_price = float(visible.close.iloc[0]), float(visible.close.iloc[-1])
        st.markdown(
            '<div class="btc-chart-summary" aria-label="차트 가격 요약">'
            f"<span>{FRAME_LABELS[chart_tf]} 확정 종가 · {candle_close(visible.index[-1], chart_tf).tz_convert(display_timezone):%m.%d %H:%M}</span>"
            f"<strong>{price_text(last_price)} <small>{escape(quote_currency)}</small></strong>"
            f"<span>표시 구간 변화 {last_price / first_price - 1:+.1%} · 초록 봉 상승 / 빨간 봉 하락</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            reader_html(
                chart_features,
                chart_tf,
                asset_code,
                tuple(average_lines) if "이동평균선" in overlays else (),
                "볼린저밴드" in overlays,
            ),
            unsafe_allow_html=True,
        )
        fig = market_chart_spec(
            chart_features.tail(420),
            display_timezone,
            tuple(average_lines) if "이동평균선" in overlays else (),
            "볼린저밴드" in overlays,
            quote_currency,
            "일목균형표" in overlays,
            detailed_chart,
            chart_bars,
            chart_tf,
            cfg.indicators.ichimoku_displacement,
        )
        st.plotly_chart(
            bind_asset(fig, asset_code),
            width="stretch",
            key="chart_01",
            theme=None,
            config=READ_CHART_CONFIG,
        )
        st.caption(
            f"{FRAME_LABELS[chart_tf]} · 확정 {len(chart_features):,}개 + 실시간 진행 중 봉 · "
            f"Binance {ASSETS[asset_code].symbol} · 약 2초마다 수신 · 지연 시 마지막 값을 유지해요."
        )
        if "일목균형표" in overlays:
            st.caption(
                "일목 구름은 확정 봉의 이동 표시예요. 현재 봉의 구름 위치는 위 잠정 분석에서 확인해요."
            )
        st.caption(
            "좌우로 짚으면 해당 봉의 가격·이평선·밴드를 함께 읽어요. 이전/다음 구간으로 이동하고, 위아래로 밀면 스크롤돼요."
        )
    else:
        st.info(
            f"{FRAME_LABELS[chart_tf]} 데이터를 받지 못했습니다. 다중 시간대 탭에서 수집 상태를 확인하세요."
        )
