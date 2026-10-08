"""Price forecast presentation: absolute prices, uncertainty and measured errors."""

from html import escape
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from btc_analyzer.analysis.forecast import ForecastReport, MIN_CALIBRATION, forecast_dates
from btc_analyzer.analysis.news_projection import project_news
from btc_analyzer.analysis.direction_outlook import direction_outlook
from btc_analyzer.analysis.direction_explanation import explain_direction
from btc_analyzer.analysis.price_explanation import explain_price
from btc_analyzer.candles import candle_close
from btc_analyzer.ui.charts import style_chart, READ_CHART_CONFIG
from btc_analyzer.ui.market_context import current_context
from btc_analyzer.data.market_context import UTC
from btc_analyzer.ui.direction_view import COLORS, direction_cards, direction_headline, direction_reason_card


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
):
    report, prediction = result.history, result.prediction
    if prediction is None:
        raise ValueError("No forecast available")
    fig = go.Figure()
    future = pd.DatetimeIndex(prediction.dates).tz_convert(timezone).strftime("%Y-%m-%d %H:%M").tolist()
    past = (
        pd.DatetimeIndex(
            forecast_dates(
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
            y=np.round(prediction.upper, 2).tolist(),
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
            y=np.round(prediction.lower, 2).tolist(),
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
            y=[round(value * report.anchor_price / 100, 2) for value in report.current_path],
            mode="lines",
            line={"color": "#53647b", "width": 2.5},
            name="확정 가격",
            hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>확정 가격</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=future,
            y=np.round(prediction.center, 2).tolist(),
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
                forecast_dates(candle_close(match.start, report.timeframe), report.timeframe, len(match.path))
            )
            .tz_convert(timezone)
            .strftime("%Y-%m-%d %H:%M")
            .tolist()
        )
        fig.add_trace(
            go.Scatter(
                x=past + future[1:],
                y=np.round(analogue_path(report, analogue_index), 2).tolist(),
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
                y=np.round(news_projection.upper, 2).tolist(),
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
                y=np.round(news_projection.lower, 2).tolist(),
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
                y=np.round(news_projection.center, 2).tolist(),
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
            fig.data[0].y = np.round(news_projection.upper, 2).tolist()
            fig.data[1].y = np.round(news_projection.lower, 2).tolist()
        for scenario in outlook.scenarios:
            leading = scenario.key in outlook.leaders
            label = scenario.label + (
                " 가정 · 사례 없음" if scenario.assumed else " · 우세" if leading else ""
            )
            fig.add_trace(
                go.Scatter(
                    x=future,
                    y=np.round(scenario.center, 2).tolist(),
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
        text=f"우세 {primary.label} · {primary.center[-1]:,.0f}"
        if primary
        else "방향 우열 없음"
        if outlook
        else f"예상 {prediction.center[-1]:,.0f}",
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
        transition={"duration": 150},
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
                y=np.round(event_projection.center, 2).tolist(),
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
                "timezone": timezone,
                "anchor": report.anchor_price,
                "baseAt": int(prediction.dates[0].timestamp() * 1000),
                "center": np.asarray(live_center).tolist(),
                "upper": np.asarray(live_range.upper).tolist(),
                "lower": np.asarray(live_range.lower).tolist(),
                "offsets": [
                    int((date - prediction.dates[0]).total_seconds() * 1000) for date in prediction.dates
                ],
                "liveIndices": [live_start, live_start + 1, live_start + 2],
                "label": "발표 조건부 경로"
                if event_projection
                else f"{primary.label} 사례 경로"
                if primary
                else "중심 경로 가정",
            }
        }
    )
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
    ).to_dict()


@st.fragment(run_every=15)
def render_prediction(
    result: ForecastReport,
    timezone: str,
    quote: str,
    period: str,
    context_values=None,
    past_values=(),
):
    prediction = result.prediction
    if prediction is None:
        st.info(result.reason)
        return
    report = result.history
    now = datetime.now(UTC)
    news = project_news(result, current_context(), now)
    use_news = st.toggle("뉴스 영향 함께 반영", value=True, key="forecast_use_news")
    active_news = news if use_news and news.effects else None
    outlook = direction_outlook(result, active_news)
    explanation = explain_direction(result, outlook, context_values, active_news, use_news)
    summary_slot = st.empty()
    if outlook is not None:
        st.markdown(direction_cards(outlook, report.anchor_price, quote), unsafe_allow_html=True)
        st.caption(
            f"보합 기준: 도착일의 기준 종가 대비 ±{outlook.threshold:.1%} · {outlook.cases}개 유사 사례를 현재 변동성에 맞춰 비교해요. 가중 비중은 미래 확률이 아니에요."
        )
        if outlook.margin < 0.1:
            st.caption("방향별 비중 차이가 작아요. 가장 큰 비중을 강조하지만 한 방향으로 단정하지 않아요.")
        st.caption(
            "사례가 없는 방향은 점선 가정으로 비교하며 우세 방향 선정에서 제외해요. 방향별 경로의 예측 정확도는 아직 검증되지 않았어요."
        )
    mode = (
        st.segmented_control(
            "전망 그래프 보기",
            ["comparison", "model"],
            format_func=lambda value: "세 방향 비교" if value == "comparison" else "모델·과거 경로",
            default="comparison",
            key="forecast_direction_view",
        )
        or "comparison"
    )
    comparison = outlook if mode == "comparison" else None
    show_range = st.toggle("예상 변동 범위 함께 보기", value=True, key="forecast_show_range")
    if st.session_state.get("forecast_analogue", 0) not in range(len(report.matches)):
        st.session_state["forecast_analogue"] = 0
    selected = st.session_state.get("forecast_analogue", 0)
    if mode == "model":
        selected = (
            st.segmented_control(
                "함께 볼 과거 경로 · 유사도 순",
                list(range(len(report.matches))),
                format_func=lambda i: f"{i + 1}위",
                default=0,
                key="forecast_analogue",
            )
            or 0
        )
        match = report.matches[selected]
        replay_price = analogue_path(report, selected)[-1]
        st.markdown(
            f'<div class="btc-replay-summary"><strong>당시에는 {match.forward_return:+.1%} 움직였어요</strong>'
            f"<span>{match.start.tz_convert(timezone):%Y.%m.%d} ~ {match.end.tz_convert(timezone):%Y.%m.%d} · 유사도 {match.similarity:.0f}점</span>"
            f"<span>같은 움직임이면 {replay_price:,.2f} {escape(quote)} · 주황색은 선택한 과거 사례의 재현이에요.</span></div>",
            unsafe_allow_html=True,
        )
    target = prediction.dates[-1].tz_convert(timezone)
    st.caption(f"예측 도착일 {target:%Y.%m.%d} · 기준 종가 {report.anchor_price:,.2f} {quote}에서 출발해요.")
    chart_slot = st.container()
    from btc_analyzer.ui.correction_view import render_correction

    correction, event, release_projection = render_correction(
        result,
        context_values or {},
        past_values,
        active_news,
        active_news or prediction,
        now,
        timezone,
        quote,
    )
    shown = release_projection or active_news or prediction
    price_explanation = explain_price(
        result, shown, period, quote, comparison, explanation if comparison is not None else None
    )
    scope = (
        "발표 조건부 예상"
        if release_projection
        else "뉴스 반영 시나리오"
        if active_news
        else "기본 모델 예상"
    )
    if result.context_values:
        st.caption(
            "추세·매수세 반영 · RSI · ADX · CMF"
            if result.model == "context"
            else "가격 패턴 중심 · 추가 지표 연구 후보는 기본 예상에 반영하지 않습니다."
        )
    move = shown.center[-1] / report.anchor_price - 1
    direction = "상승 쪽" if move >= 0.005 else "하락 쪽" if move <= -0.005 else "횡보 쪽"
    price_label = f"{shown.center[-1]:,.2f}"
    range_label = (
        "발표 조건부 범위"
        if release_projection
        else "뉴스 가정 포함 범위"
        if active_news
        else "예상 변동 범위"
    )
    note = f"{escape(quote)} · 기준 종가 대비 {move:+.1%}"
    if comparison is not None:
        direction, scope = direction_headline(comparison), "방향별 재현"
        shown = active_news or prediction
        range_label = "뉴스 가정 포함 범위" if active_news else "기술 모델 변동 범위"
        leaders = [scenario for scenario in comparison.scenarios if scenario.key in comparison.leaders]
        price_label = f"{leaders[0].center[-1]:,.2f}" if len(leaders) == 1 else "한 방향으로 좁히기 어려워요"
        note = (
            f"{escape(quote)} · 기준 종가 대비 {leaders[0].center[-1] / report.anchor_price - 1:+.1%}"
            if len(leaders) == 1
            else "세 카드의 도착 가격을 함께 비교해 주세요."
        )
    status = f"{len(result.validation)}회 과거 검증" if result.mae is not None else "검증 자료 부족"
    summary_slot.markdown(
        (
            f'<div class="btc-forecast-cards btc-direction-summary" aria-label="예측 요약"><article>'
            f"<p>{escape(period)} 뒤 · {direction}</p><strong>{price_label}</strong><span>{note}</span>"
            f"<span>선정 이유: {escape(explanation.selection) if explanation else '근거 확인 중'}</span>"
            f"<span>{range_label} {shown.lower[-1]:,.0f} ~ {shown.upper[-1]:,.0f} {escape(quote)} · {status}</span>"
            f"<span>방향별 경로는 미검증 · 비중은 확률이 아니에요</span></article></div>"
        )
        if comparison
        else (
            f'<div class="btc-forecast-cards" aria-label="예측 요약">'
            f"<article><p>{escape(period)} 뒤 {scope} · {direction}</p><strong>{price_label}</strong>"
            f"<span>{note}</span></article>"
            f"<article><p>{range_label}</p><strong>{shown.lower[-1]:,.0f} ~ {shown.upper[-1]:,.0f}</strong>"
            f"<span>{escape(quote)} · 보장된 가격 범위가 아니에요</span></article>"
            f"<article><p>기술 모델의 과거 검증</p><strong>{status}</strong>"
            f"<span>{len(report.matches)}개 유사 사례 · 방향별 경로·뉴스·발표 가정은 미검증</span></article></div>"
        ),
        unsafe_allow_html=True,
    )
    if active_news:
        st.markdown(
            f'<div class="btc-news-scenario"><strong>뉴스 가정으로 기본 전망 대비 {news.shift:+.2%} 조정</strong><br>기본 예상 {prediction.center[-1]:,.2f} {escape(quote)} → 뉴스 반영 {news.center[-1]:,.2f} {escape(quote)}<br>제목 기반의 제한된 가정이에요. 뉴스 반영 후 정확도가 높아졌다는 검증은 아직 없습니다.</div>',
            unsafe_allow_html=True,
        )
        with st.expander("어떤 뉴스가 전망에 들어갔나요?"):
            for effect in news.effects:
                label = (
                    "우호 가정"
                    if effect.direction > 0
                    else "부담 가정"
                    if effect.direction < 0
                    else "불확실성만 반영"
                )
                st.write(f"**{effect.topic} · {label}** — {effect.explanation}")
                for i, url in enumerate(effect.urls[:3]):
                    st.markdown(f"[반영 근거 {i + 1}]({url})")
            st.caption(f"뉴스 확인 {news.as_of:%Y.%m.%d %H:%M} UTC · {news.version} · {news.reason}")
            st.caption(
                "같은 주제는 한 번만 반영하며 상반된 보도는 중립 처리합니다. 3일에 걸쳐 반영되는 가격 수준 조정 가정(최대 약 ±4.1%)이며 미래 뉴스·경제지표 결과를 예측하지 않습니다. 이미 시세에 반영된 정도를 제목만으로 알 수는 없습니다."
            )
    elif use_news:
        st.caption(news.reason)
    st.caption("과거 검증과 오차 보정은 뉴스 조정 전 기술 모델만 평가한 결과예요.")
    if result.mae is None or len(result.validation) < MIN_CALIBRATION:
        st.info("과거 검증이 12회 미만이라 신뢰도를 충분히 평가하기 어렵습니다. 참고용 예상으로 봐 주세요.")
    elif result.mae >= result.baseline_mae:
        st.warning(
            "이 설정은 과거 검증에서 ‘가격 유지’ 가정보다 오차가 컸습니다. 예측의 방향 판단을 신중하게 보세요."
        )
    else:
        improvement = 1 - result.mae / result.baseline_mae
        st.caption(
            f"과거 검증에서 가격 유지 가정보다 평균 오차가 {improvement:.0%} 작았습니다. 미래 성능을 보장하지 않습니다."
        )
    with chart_slot:
        st.markdown(
            '<section id="btc-live-forecast" class="btc-live-forecast" aria-label="실시간 조건부 예측">'
            "<p>현재가에서 출발하는 예상 · 실시간</p><strong>시세 연결 중…</strong>"
            '<span class="btc-live-status">시세 수신 대기</span>'
            '<p class="btc-live-forecast-range"></p><p class="btc-live-forecast-reason"></p>'
            "<p>초록 점선은 현재가 기준 조건부 경로예요. 기존 예상/과거 재현은 기준 종가를 유지하며, "
            "과거 성적은 확정 모델만 평가한 결과예요.</p></section>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            prediction_spec(
                result,
                timezone,
                quote,
                show_range,
                selected if mode == "model" else None,
                active_news,
                correction,
                event,
                release_projection,
                comparison,
            ),
            width="stretch",
            key="future_price_chart",
            theme=None,
            config=READ_CHART_CONFIG,
        )
        if price_explanation is not None:
            st.markdown(
                direction_reason_card(
                    price_explanation, price=result.technical is not None, comparison=comparison is not None
                ),
                unsafe_allow_html=True,
            )
        st.caption(
            "초록은 상승, 회색은 보합, 빨강은 하락 경로예요. 가장 우세한 비중을 굵게 표시하며 사례 없는 방향은 점선 가정이에요."
            if comparison
            else "회색은 확정 가격, 파란 점선은 모델 예상, 주황색은 선택한 과거 사례의 실제 움직임을 현재 가격에 맞춘 경로예요."
        )
        if active_news:
            st.caption(
                "현재 뉴스의 제한된 가격 가정을 방향별 경로에도 반영했어요."
                if comparison
                else "보라색은 최근 뉴스의 조건부 가격 시나리오예요."
            )
        st.caption(
            "옅은 영역은 변동 범위, 주황 세로 구간은 과거 조정 시점, 갈색 선은 발표 시각이에요. 분홍 점선은 발표 결과의 별도 가정이며 방향 비중을 바꾸지 않아요."
        )
    st.caption(
        f"기준 종가 {report.anchor_price:,.2f} {quote} · {report.query_end.tz_convert(timezone):%Y.%m.%d %H:%M} · {timezone}"
    )
    if prediction.calibrated_cases:
        st.caption(
            f"변동 범위에 앞선 {prediction.calibrated_cases}회 예측의 시점별 오차를 반영했습니다. 특정 포함 확률을 보장하지 않습니다."
        )
    else:
        st.caption(
            "변동 범위는 유사 사례의 분산과 현재 변동성으로 추정했습니다. 과거 오차 보정에 필요한 12회 검증이 아직 부족합니다."
        )
