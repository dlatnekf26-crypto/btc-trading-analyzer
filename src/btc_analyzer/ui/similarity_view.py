"""Focused, percentage-based analogue comparison with distinct before/after panels."""

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from btc_analyzer.analysis.forecast import forecast_dates
from btc_analyzer.candles import candle_close
from btc_analyzer.ui.charts import style_chart, READ_CHART_CONFIG


def comparison_chart(report, timezone: str, selected: int = 0, all_matches: bool = False):
    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.23,
        subplot_titles=("① 지금과 얼마나 닮았나요?", "② 그 뒤 실제 가격은 어떻게 됐나요?"),
    )
    before = list(range(1 - report.window, 1))
    colors = ("#16a085", "#916bd1", "#d99520", "#d95d7b", "#7889a4")
    chosen = range(len(report.matches)) if all_matches else (selected,)
    for number in chosen:
        match = report.matches[number]
        dates = pd.DatetimeIndex(
            forecast_dates(candle_close(match.start, report.timeframe), report.timeframe, len(match.path))
        )
        actual_dates = dates.tz_convert(timezone).strftime("%Y.%m.%d %H:%M").tolist()
        label = f"과거 {number + 1} · {match.start.tz_convert(timezone):%Y.%m.%d}"
        color = colors[number % len(colors)]
        fig.add_trace(
            go.Scatter(
                x=before,
                y=np.round(np.array(match.path[: report.window]) - 100, 3).tolist(),
                customdata=actual_dates[: report.window],
                name=label,
                legendgroup=str(number),
                mode="lines",
                line={"color": color, "width": 2.5},
                hovertemplate="%{customdata}<br>비교 종가 대비 %{y:+.2f}%<extra>%{fullData.name}</extra>",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=list(range(report.forward + 1)),
                y=np.round(np.array(match.path[report.window - 1 :]) - 100, 3).tolist(),
                customdata=actual_dates[report.window - 1 :],
                name=label + " · 이후 실제",
                legendgroup=str(number),
                showlegend=False,
                mode="lines",
                line={"color": color, "width": 2.5},
                hovertemplate="%{customdata}<br>당시 이후 변화 %{y:+.2f}%<extra>%{fullData.name}</extra>",
            ),
            row=2,
            col=1,
        )
        if not all_matches:
            fig.add_annotation(
                x=report.forward,
                y=match.forward_return * 100,
                text=f"{match.forward_return:+.1%}",
                showarrow=False,
                xanchor="right",
                yshift=18,
                font={"color": color, "size": 13},
                row=2,
                col=1,
            )
    dates = pd.DatetimeIndex(
        forecast_dates(candle_close(report.query_start, report.timeframe), report.timeframe, report.window)
    )
    fig.add_trace(
        go.Scatter(
            x=before,
            y=np.round(np.array(report.current_path) - 100, 3).tolist(),
            customdata=dates.tz_convert(timezone).strftime("%Y.%m.%d %H:%M").tolist(),
            name="지금 흐름",
            mode="lines",
            line={"color": "#3182f6", "width": 3.5},
            hovertemplate="%{customdata}<br>비교 종가 대비 %{y:+.2f}%<extra>지금 흐름</extra>",
        ),
        row=1,
        col=1,
    )
    style_chart(fig, height=580)
    fig.update_layout(
        margin={"t": 110, "b": 30, "l": 12, "r": 16},
        legend={"y": 1.10, "yanchor": "bottom"},
        uirevision=f"similarity-{report.timeframe}-{report.window}-{report.forward}-{selected}-{all_matches}",
    )
    fig.update_yaxes(
        title="변화율", ticksuffix="%", tickformat="+.0f", zeroline=True, zerolinecolor="#b3bfd1"
    )
    fig.update_xaxes(
        tickvals=[1 - report.window, 0],
        ticktext=["비교 시작", "비교 시점"],
        range=[1 - report.window - report.window * 0.04, report.window * 0.1],
        row=1,
        col=1,
    )
    unit = {"1h": "시간", "4h": "시간", "1d": "일", "1w": "주", "1M": "개월"}[report.timeframe]
    factor = 4 if report.timeframe == "4h" else 1
    ticks = sorted({0, report.forward // 2, report.forward})
    fig.update_xaxes(
        range=[-report.forward * 0.04, report.forward * 1.1],
        tickvals=ticks,
        ticktext=["그때" if tick == 0 else f"{tick * factor}{unit} 뒤" for tick in ticks],
        row=2,
        col=1,
    )
    return fig


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False)
def comparison_spec(report, timezone, selected, all_matches):
    return comparison_chart(report, timezone, selected, all_matches).to_dict()


@st.fragment
def render_comparison(report, timezone, period):
    # Switching a case reuses the captured report; it does not fetch or forecast again.
    st.caption("파랑은 지금 흐름 · 다른 색은 닮았던 과거예요.")
    all_matches = st.toggle("모든 사례 겹쳐보기", key="similarity_show_all")
    selected = st.selectbox(
        "비슷했던 시기",
        range(len(report.matches)),
        format_func=lambda index: (
            f"{index + 1}위 · {report.matches[index].start.tz_convert(timezone):%Y.%m.%d} · 유사도 {report.matches[index].similarity:.0f}점"
        ),
        key=f"similarity_case_{report.timeframe}_{report.window}_{report.forward}_{len(report.matches)}",
    )
    match = report.matches[selected]
    st.markdown(
        '<div class="btc-match-cards" aria-label="선택한 과거 요약">'
        f"<article><span>닮은 정도</span><strong>{match.similarity:.0f}<small> / 100</small></strong></article>"
        f"<article><span>{escape(period)} 뒤 실제 변화</span><strong>{match.forward_return:+.1%}</strong></article>"
        f"<article><span>최대 하락 · 저가 기준</span><strong>{match.lowest_return:.1%}</strong></article></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"선택한 과거: {match.start.tz_convert(timezone):%Y.%m.%d} ~ {candle_close(match.end, report.timeframe).tz_convert(timezone):%Y.%m.%d} · 이후 관찰 종료 {match.observed_until.tz_convert(timezone):%Y.%m.%d}"
    )
    st.plotly_chart(
        comparison_spec(report, timezone, selected, all_matches),
        width="stretch",
        key="historical_similarity_chart",
        theme=None,
        config=READ_CHART_CONFIG,
    )
    st.caption(
        "가격 수준이 달라도 모양을 비교하도록 각 구간 마지막 종가를 0%에 맞췄어요. 아래 선은 당시 이후 실제 가격이며 현재의 예측선이 아닙니다."
    )
    st.caption(
        f"{len(report.matches)}개 사례 · 유사도 순위로 선택했으며 이후 성과로 정렬하지 않았어요. 위·아래 차트는 각각의 기간과 변화율 눈금을 사용합니다."
    )
