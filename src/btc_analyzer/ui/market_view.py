"""Chart controls reuse closed-candle features without a separate strategy run."""

from html import escape

import streamlit as st

from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

from btc_analyzer.config import COMPOSITE_TIMEFRAMES
from btc_analyzer.candles import candle_close
from btc_analyzer.strategy.composite import FRAME_LABELS
from btc_analyzer.ui.charts import price_chart


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
        uirevision=f"market-{features.attrs.get('timeframe')}-{bars}", transition={"duration": 150}
    )
    fig.update_xaxes(
        tickformat="%m.%d<br>%H:%M" if timeframe in ("1h", "4h") else "%y.%m.%d", nticks=5, row=2, col=1
    )
    return fig.to_dict()


@st.fragment
def render_market_chart(*, bundle, enriched, cfg, display_timezone, average_lines, quote_currency):
    st.markdown('<p class="btc-section-label">필요한 만큼, 자유롭게</p>', unsafe_allow_html=True)
    st.subheader("차트로 확인하기")
    chart_tf = st.segmented_control(
        "차트 시간대",
        COMPOSITE_TIMEFRAMES,
        default="1d",
        format_func=FRAME_LABELS.get,
        key="price_chart_timeframe",
    )
    chart_tf = chart_tf or "1d"
    chart_view = st.segmented_control("차트 보기", ["간편", "상세"], default="간편") or "간편"
    overlays = st.pills(
        "겹쳐 볼 지표",
        ["일목균형표", "이동평균선", "볼린저밴드"],
        selection_mode="multi",
        default=["일목균형표"],
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
            f"<strong>{last_price:,.2f} <small>{escape(quote_currency)}</small></strong>"
            f"<span>표시 구간 변화 {last_price / first_price - 1:+.1%} · 초록 봉 상승 / 빨간 봉 하락</span></div>",
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
            fig,
            width="stretch",
            key="chart_01",
            theme=None,
            config={
                "displaylogo": False,
                "displayModeBar": detailed_chart,
                "scrollZoom": False,
                "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"] if detailed_chart else [],
                "toImageButtonOptions": {"format": "png", "filename": "btc-signal-lab"},
            },
        )
        st.caption(
            f"{FRAME_LABELS[chart_tf]} · {len(chart_features):,}개 확정 봉 · 실시간 현재가는 상단에서 확인하세요."
        )
        if "일목균형표" in overlays:
            st.caption("일목 구름은 과거 가격을 이동 표시한 지표이며 미래 가격 예측이 아닙니다.")
        if detailed_chart:
            st.caption(
                "상세 차트의 도구로 확대, 선·영역 그리기, 이미지 저장을 할 수 있어요. 그린 도형은 분석 신호를 바꾸지 않아요."
            )
    else:
        st.info(
            f"{FRAME_LABELS[chart_tf]} 데이터를 받지 못했습니다. 다중 시간대 탭에서 수집 상태를 확인하세요."
        )
