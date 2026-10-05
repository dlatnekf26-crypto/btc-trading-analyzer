"""Chart-only fragment: controls do not rerun collection, signals or paper trading."""

from html import escape

import streamlit as st

from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

from btc_analyzer.config import COMPOSITE_TIMEFRAMES, MTF_MAP
from btc_analyzer.candles import candle_close
from btc_analyzer.strategy.composite import FRAME_LABELS
from btc_analyzer.ui.analysis_cache import research_analysis
from btc_analyzer.ui.charts import price_chart
from btc_analyzer.ui.presentation import ichimoku_cards


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def market_chart_spec(
    features,
    analysis,
    timezone,
    averages,
    bands,
    quote,
    ichimoku,
    detailed,
    zones,
    bars,
    timeframe,
    displacement,
):
    features = features.copy(deep=False)
    features.attrs = {**features.attrs, "timeframe": timeframe, "ichimoku_displacement": displacement}
    fig = price_chart(
        features,
        analysis,
        timezone,
        averages,
        bands,
        quote=quote,
        ichimoku=ichimoku,
        ichimoku_detail=detailed,
        zones_visible=zones,
        levels_visible=zones,
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
def render_market_chart(*, bundle, enriched, cfg, display_timezone, average_lines, quote_currency, combined):
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
        ["일목균형표", "이동평균선", "볼린저밴드", "가격 영역"],
        selection_mode="multi",
        default=["일목균형표"],
    )
    detailed_chart = chart_view == "상세"
    chart_bars = 120
    if detailed_chart:
        chart_bars = st.select_slider("표시할 봉 수", options=[60, 120, 240, 400], value=240)
    chart_raw = bundle.get(chart_tf)
    if chart_raw is not None and not chart_raw.empty:
        chart_features, chart_analysis = research_analysis(
            {tf: bundle[tf] for tf in MTF_MAP[chart_tf] if tf in bundle and not bundle[tf].empty},
            chart_tf,
            cfg,
            enriched,
        )
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
            chart_analysis,
            display_timezone,
            tuple(average_lines) if "이동평균선" in overlays else (),
            "볼린저밴드" in overlays,
            quote_currency,
            "일목균형표" in overlays,
            detailed_chart,
            "가격 영역" in overlays,
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
            f"{FRAME_LABELS[chart_tf]} · {len(chart_features):,}개 확정 봉. 이 차트의 관찰용 가격선은 종합 매수·매도 신호와 별개입니다."
        )
        if "일목균형표" in overlays:
            st.caption(
                "앞으로 그려진 일목 구름은 지금까지의 데이터로 계산한 표시 영역이에요. 미래 가격 예측이 아니에요."
            )
            st.subheader(f"일목균형표, 이렇게 읽어요 · {FRAME_LABELS[chart_tf]}")
            st.markdown(
                ichimoku_cards(
                    combined.frames[chart_tf].indicators,
                    displacement=cfg.indicators.ichimoku_displacement,
                ),
                unsafe_allow_html=True,
            )
            with st.expander("일목균형표 사용법"):
                st.write(
                    "간편 보기에서는 구름을 먼저 확인해요. 상세 보기에서는 전환선·기준선·후행스팬을 함께 볼 수 있어요."
                )
                st.write(
                    "선행 구름은 지금까지의 고가·저가로 계산한 값을 미래 축에 옮겨 그린 영역이에요. 미래 가격 예측이 아니에요."
                )
                st.write(
                    "후행스팬은 현재 종가를 과거 축에 그려요. 신호는 현재 종가와 이미 확정된 과거 종가를 비교하므로 미래 가격을 참조하지 않아요."
                )
                st.write("일목 하나만으로 신호를 만들지 않고 기존 지표와 다섯 시간대의 조건을 함께 확인해요.")
        if detailed_chart:
            st.caption(
                "상세 차트의 도구로 확대, 선·영역 그리기, 이미지 저장을 할 수 있어요. 그린 도형은 분석 신호를 바꾸지 않아요."
            )
    else:
        st.info(
            f"{FRAME_LABELS[chart_tf]} 데이터를 받지 못했습니다. 다중 시간대 탭에서 수집 상태를 확인하세요."
        )
