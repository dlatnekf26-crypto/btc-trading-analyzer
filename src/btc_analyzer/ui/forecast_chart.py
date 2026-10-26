"""Forecast figure construction; presentation controls live in forecast_view.py."""

from html import escape
from btc_analyzer.assets import SESSION_MARKETS, price_text
from btc_analyzer.analysis.ai_forecast import forecast_key

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from btc_analyzer.analysis.forecast import ForecastReport, forecast_dates
from btc_analyzer.analysis.projected_indicators import project_indicators, projection_fields
from btc_analyzer.candles import candle_close
from btc_analyzer.ui.charts import style_chart
from btc_analyzer.ui.direction_view import COLORS


def analogue_path(report, index=0):
    """Rebase one complete observed path without shrinking or volatility scaling."""
    match = report.matches[index]
    return tuple(report.anchor_price * np.asarray(match.path) / 100)


def prediction_chart(
    result: ForecastReport,
    timezone: str,
    quote: str,
    show_range: bool = True,
    analogue_index: int | None = 0,
    news_projection=None,
    correction=None,
    event=None,
    event_projection=None,
    outlook=None,
    indicator_seed=None,
):
    report, prediction = result.history, result.prediction
    decimals = 6 if report.anchor_price < 0.01 else 4 if report.anchor_price < 10 else 2
    if prediction is None:
        raise ValueError("No forecast available")
    fig = go.Figure()
    future = pd.DatetimeIndex(prediction.dates).tz_convert(timezone).strftime("%Y-%m-%d %H:%M").tolist()
    past = (
        pd.DatetimeIndex(
            report.current_dates
            or forecast_dates(
                candle_close(report.query_start, report.timeframe), report.timeframe, report.window
            )
        )
        .tz_convert(timezone)
        .strftime("%Y-%m-%d %H:%M")
        .tolist()
    )
    fig.add_trace(
        go.Scatter(
            x=future,
            y=np.round(prediction.upper, decimals).tolist(),
            visible=show_range,
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
            name="범위 상단",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=future,
            y=np.round(prediction.lower, decimals).tolist(),
            visible=show_range,
            mode="lines",
            line={"width": 0},
            fill="tonexty",
            fillcolor="rgba(49,130,246,0.13)",
            name="예상 변동 범위",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=past,
            y=[round(value * report.anchor_price / 100, decimals) for value in report.current_path],
            mode="lines",
            line={"color": "#53647b", "width": 2.5},
            name="확정 가격",
            hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>확정 가격</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=future,
            y=np.round(prediction.center, decimals).tolist(),
            mode="lines",
            name="예상 중심 경로",
            line={"color": "#3182f6", "width": 3, "dash": "dash"},
            hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>모델 예상</extra>",
        )
    )
    if analogue_index is not None:
        match = report.matches[analogue_index]
        observed = (
            pd.DatetimeIndex(
                match.dates
                or forecast_dates(
                    candle_close(match.start, report.timeframe), report.timeframe, len(match.path)
                )
            )
            .tz_convert(timezone)
            .strftime("%Y-%m-%d %H:%M")
            .tolist()
        )
        fig.add_trace(
            go.Scatter(
                x=past + future[1:],
                y=np.round(analogue_path(report, analogue_index), decimals).tolist(),
                customdata=observed,
                mode="lines",
                name="과거 사례 재현",
                line={"color": "#ed9a24", "width": 2, "dash": "dot"},
                hovertemplate=f"환산 %{{y:,.2f}} {escape(quote)}<br>당시 %{{customdata}}<extra>과거 실제 경로</extra>",
            )
        )
    if news_projection is not None and news_projection.effects:
        fig.add_trace(
            go.Scatter(
                x=future,
                y=np.round(news_projection.upper, decimals).tolist(),
                mode="lines",
                line={"width": 0},
                visible=show_range,
                showlegend=False,
                hoverinfo="skip",
                name="뉴스 가정 상단",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future,
                y=np.round(news_projection.lower, decimals).tolist(),
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor="rgba(139,92,246,0.08)",
                visible=show_range,
                showlegend=False,
                hoverinfo="skip",
                name="뉴스 가정 범위",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=future,
                y=np.round(news_projection.center, decimals).tolist(),
                mode="lines",
                line={"color": "#8b5cf6", "width": 3},
                name="뉴스 반영 시나리오",
                hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>뉴스 가정 · 미검증</extra>",
            )
        )
    if outlook is not None:
        # Send only the displayed paths. The model view uses a separate cached
        # spec, preserving its original values without hidden duplicate traces.
        fig.data = tuple(
            trace for trace in fig.data if trace.name in ("범위 상단", "예상 변동 범위", "확정 가격")
        )
        fig.data[1].showlegend = False
        if news_projection is not None and news_projection.effects:
            fig.data[0].y = np.round(news_projection.upper, decimals).tolist()
            fig.data[1].y = np.round(news_projection.lower, decimals).tolist()
        for scenario in outlook.scenarios:
            leading = scenario.key in outlook.leaders
            label = scenario.label + (
                " 가정 · 사례 없음" if scenario.assumed else " · 우세" if leading else ""
            )
            fig.add_trace(
                go.Scatter(
                    x=future,
                    y=np.round(scenario.center, decimals).tolist(),
                    mode="lines",
                    name=label,
                    line={
                        "color": COLORS[scenario.key],
                        "width": 3.5 if leading else 1.7,
                        "dash": "dot" if scenario.assumed else "solid",
                    },
                    opacity=1 if leading else 0.7,
                    meta={"direction": scenario.key, "assumed": scenario.assumed, "share": scenario.share},
                    hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>{label} · 가중 비중 {scenario.share:.0%}</extra>",
                )
            )
    fig.add_shape(
        type="line",
        x0=future[0],
        x1=future[0],
        y0=0,
        y1=1,
        yref="paper",
        line={"color": "#b3bfd1", "dash": "dot", "width": 1},
    )
    fig.add_annotation(
        x=future[0],
        y=1.03,
        yref="paper",
        text="예측 시작",
        showarrow=False,
        xanchor="left",
        font={"size": 11, "color": "#66758b"},
    )
    primary = (
        next((scenario for scenario in outlook.scenarios if scenario.key in outlook.leaders), None)
        if outlook and len(outlook.leaders) == 1
        else None
    )
    fig.add_annotation(
        x=future[-1],
        y=primary.center[-1] if primary else prediction.center[-1],
        text=f"우세 {primary.label} · {price_text(primary.center[-1])}"
        if primary
        else "방향 우열 없음"
        if outlook
        else f"예상 {price_text(prediction.center[-1])}",
        showarrow=False,
        xanchor="right",
        yshift=18,
        font={"size": 12, "color": COLORS[primary.key] if primary else "#3182f6"},
        bgcolor="rgba(255,255,255,0.85)",
    )
    style_chart(fig, height=440)
    fig.update_layout(
        uirevision=f"forecast-{report.timeframe}-{report.window}-{report.forward}",
        margin={"t": 60, "l": 12, "r": 12},
        legend={"y": 1.02, "yanchor": "bottom", "traceorder": "normal"},
    )
    fig.update_xaxes(
        title=f"확정 가격 → {'세 방향 비교' if outlook else '예상 경로'} · {timezone}",
        tickformat="%m.%d<br>%H:%M" if report.timeframe in ("1h", "4h") else "%y.%m.%d",
        nticks=5,
    )
    if correction is not None and correction.window_start is not None:
        fig.add_vrect(
            x0=correction.window_start.tz_convert(timezone).strftime("%Y-%m-%d %H:%M"),
            x1=correction.window_end.tz_convert(timezone).strftime("%Y-%m-%d %H:%M"),
            fillcolor="#f59f35",
            opacity=0.09,
            line_width=0,
            layer="below",
        )
    if event is not None:
        release = pd.Timestamp(event.at).tz_convert(timezone).strftime("%Y-%m-%d %H:%M")
        fig.add_shape(
            type="line",
            x0=release,
            x1=release,
            y0=0,
            y1=1,
            yref="paper",
            line={"color": "#936624", "dash": "dot", "width": 1},
        )
        fig.add_annotation(
            x=release,
            y=0.90,
            yref="paper",
            text="주요 발표",
            showarrow=False,
            font={"size": 11, "color": "#936624"},
            bgcolor="rgba(255,255,255,0.85)",
        )
    if event_projection is not None:
        fig.add_trace(
            go.Scatter(
                x=future,
                y=np.round(event_projection.center, decimals).tolist(),
                name="발표 조건부 경로",
                mode="lines",
                line={"color": "#d84f86", "width": 2, "dash": "dash"},
                hovertemplate=f"%{{y:,.2f}} {quote}<extra>발표 결과 가정 · 미검증</extra>",
            )
        )
    # Keep the validated model, direction shares and historical replay intact.
    # This additional browser path expresses the same return assumptions from
    # the latest price; it is not a recalibrated or independently tested model.
    live_center = (
        event_projection.center
        if event_projection
        else primary.center
        if primary
        else (news_projection or prediction).center
    )
    live_range = event_projection or news_projection or prediction
    live_start = len(fig.data)
    if report.market not in SESSION_MARKETS:
        for name, fill in (("실시간 범위 상단", False), ("실시간 조건부 범위", True)):
            fig.add_trace(
                go.Scatter(
                    x=future,
                    y=[None] * len(future),
                    mode="lines",
                    name=name,
                    line={"width": 0},
                    fill="tonexty" if fill else None,
                    fillcolor="rgba(16,168,119,0.09)",
                    showlegend=False,
                    visible=show_range,
                    hoverinfo="skip",
                )
            )
        fig.add_trace(
            go.Scatter(
                x=future,
                y=[None] * len(future),
                mode="lines",
                name="실시간 출발 · 조건부",
                line={"color": "#09845c", "width": 3, "dash": "dash"},
                hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>현재가 기준 · 기존 수익률 경로 가정</extra>",
            )
        )
    fig.update_layout(
        meta={
            "btcLive": {
                "kind": "forecast",
                "aiBasis": forecast_key(result),
                "timezone": timezone,
                "anchor": report.anchor_price,
                "baseAt": int(prediction.dates[0].timestamp() * 1000),
                "center": np.asarray(live_center).tolist(),
                "upper": np.asarray(live_range.upper).tolist(),
                "lower": np.asarray(live_range.lower).tolist(),
                "offsets": [
                    int((date - prediction.dates[0]).total_seconds() * 1000) for date in prediction.dates
                ],
                "liveIndices": []
                if report.market in SESSION_MARKETS
                else [live_start, live_start + 1, live_start + 2],
                "label": "발표 조건부 경로"
                if event_projection
                else f"{primary.label} 사례 경로"
                if primary
                else "중심 경로 가정",
            }
        }
    )
    if indicator_seed:
        projected = project_indicators(indicator_seed, tuple(live_center))
        colors = ("#dd9b24", "#3182f6", "#8c65da", "#94a3b8", "#6682a6", "#94a3b8")
        overlays = {}
        labels = {
            "bb_upper": "예상 볼린저 상단",
            "bb_middle": "예상 볼린저 중심",
            "bb_lower": "예상 볼린저 하단",
        }
        for field, color in zip(projection_fields(indicator_seed), colors):
            overlays[str(len(fig.data))] = field
            label = (
                "예상 " + field.upper().replace("_", " ")
                if field.startswith(("ema_", "sma_"))
                else labels[field]
            )
            fig.add_trace(
                go.Scatter(
                    x=future,
                    y=projected[field],
                    name=label,
                    mode="lines",
                    line={"color": color, "width": 1.3, "dash": "dot"},
                    hoverinfo="skip",
                )
            )
        fig.layout.meta["btcLive"].update(indicatorSeed=indicator_seed, indicatorOverlays=overlays)
    fig.update_layout(hovermode=False)
    fig.update_yaxes(title=quote, tickformat=",.0f")
    return fig


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False)
def prediction_spec(
    result,
    timezone,
    quote,
    show_range,
    analogue_index=0,
    news_projection=None,
    correction=None,
    event=None,
    event_projection=None,
    outlook=None,
    indicator_seed=None,
):
    return prediction_chart(
        result,
        timezone,
        quote,
        show_range,
        analogue_index,
        news_projection,
        correction,
        event,
        event_projection,
        outlook,
        indicator_seed,
    ).to_dict()
