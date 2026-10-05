"""Price forecast presentation: absolute prices, uncertainty and measured errors."""

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from btc_analyzer.analysis.forecast import ForecastReport, MIN_CALIBRATION, MODEL_VERSION
from btc_analyzer.candles import candle_shift
from btc_analyzer.ui.charts import style_chart


def prediction_chart(result: ForecastReport, timezone: str, quote: str):
    report, prediction = result.history, result.prediction
    if prediction is None:
        raise ValueError("No forecast available")
    fig = go.Figure()
    future = [date.tz_convert(timezone).isoformat() for date in prediction.dates]
    past = [
        candle_shift(report.query_start, report.timeframe, i + 1).tz_convert(timezone).isoformat()
        for i in range(report.window)
    ]
    fig.add_trace(
        go.Scatter(
            x=future,
            y=prediction.upper,
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
            y=prediction.lower,
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
            y=prediction.center,
            mode="lines",
            name="예상 중심 경로",
            line={"color": "#3182f6", "width": 3, "dash": "dash"},
            hovertemplate=f"%{{y:,.2f}} {escape(quote)}<extra>모델 예상</extra>",
        )
    )
    style_chart(fig, height=420)
    fig.update_layout(
        uirevision=f"forecast-{report.timeframe}-{report.window}-{report.forward}",
        margin={"t": 60, "l": 12, "r": 12},
        transition={"duration": 150},
        legend={"y": 1.02, "yanchor": "bottom"},
    )
    fig.update_xaxes(title=f"확정 가격 ← 기준 시점 → 모델 예상 · {timezone}")
    fig.update_yaxes(title=quote, tickformat=",.0f")
    return fig


def render_prediction(
    result: ForecastReport, timezone: str, quote: str, period: str, *, demo: bool, exchange: str, symbol: str
):
    prediction = result.prediction
    if prediction is None:
        st.info(result.reason)
        return
    report = result.history
    move = prediction.center[-1] / report.anchor_price - 1
    direction = "상승 쪽" if move >= 0.005 else "하락 쪽" if move <= -0.005 else "횡보 쪽"
    status = f"{len(result.validation)}회 과거 검증" if result.mae is not None else "검증 자료 부족"
    st.markdown(
        f'<div class="btc-forecast-cards" aria-label="예측 요약">'
        f"<article><p>{escape(period)} 뒤 예상 · {direction}</p><strong>{prediction.center[-1]:,.2f}</strong>"
        f"<span>{escape(quote)} · 기준 종가 대비 {move:+.1%}</span></article>"
        f"<article><p>예상 변동 범위</p><strong>{prediction.lower[-1]:,.0f} ~ {prediction.upper[-1]:,.0f}</strong>"
        f"<span>{escape(quote)} · 보장된 가격 범위가 아니에요</span></article>"
        f"<article><p>예측을 얼마나 믿을 수 있나요?</p><strong>{status}</strong>"
        f"<span>{len(report.matches)}개 유사 사례 · 가중 유효 {prediction.effective_cases:.1f}개</span></article></div>",
        unsafe_allow_html=True,
    )
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
    st.plotly_chart(
        prediction_chart(result, timezone, quote),
        width="stretch",
        key="future_price_chart",
        theme=None,
        config={"displaylogo": False, "displayModeBar": False, "scrollZoom": False},
    )
    st.caption(
        "회색은 실제 확정 가격, 파란 점선은 현재 가격에 맞춘 모델 예상, 옅은 영역은 예상 변동 범위예요. 매수·매도 신호는 상단의 별도 위험 조건으로 판단합니다."
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
    details = st.expander(
        "과거 예측 성적 · 어떻게 계산했나요?", key="forecast_validation_details", on_change="rerun"
    )
    if details.open:
        with details:
            st.write(
                f"모델 {MODEL_VERSION} · 유사도 가중 평균 경로를 현재 변동성에 맞추고, 사례 수와 유사도가 낮을수록 가격 유지 쪽으로 줄여 계산합니다."
            )
            st.write(
                "각 과거 시점에서 당시까지 확정된 자료만으로 예측하고 이후 실제 종가와 비교합니다. 검증 기간은 서로 겹치지 않으며, 변동 범위 보정에도 앞선 검증의 오차만 사용합니다."
            )
            if result.mae is not None:
                a, b, c = st.columns(3)
                a.metric("평균 변화율 오차", f"{result.mae * 100:.2f}%p")
                b.metric("가격 유지 가정 오차", f"{result.baseline_mae * 100:.2f}%p")
                c.metric(
                    "방향 적중률",
                    f"{result.directional_accuracy:.0%}"
                    if result.directional_accuracy is not None
                    else "평가 불가",
                )
                st.caption(
                    "방향 적중률은 실제 변화가 ±0.5% 이상인 검증에서 평가합니다. 그보다 작은 모델 예상은 횡보로 처리합니다."
                )
                if result.coverage is not None:
                    count = sum(case.calibration_cases >= MIN_CALIBRATION for case in result.validation)
                    st.caption(
                        f"오차 보정이 가능했던 {count}회 검증의 종가 범위 포함률 {result.coverage:.0%}. 모든 미래 가격이나 경로가 이 안에 든다는 뜻은 아니에요."
                    )
                rows = pd.DataFrame(
                    [
                        {
                            "자료 모드": "Demo" if demo else "Live",
                            "거래소": exchange,
                            "페어": symbol,
                            "시간대": report.timeframe,
                            "모델": MODEL_VERSION,
                            "예측 시점": case.origin.tz_convert(timezone).strftime("%Y.%m.%d %H:%M"),
                            "실제 확인 시점": case.observed_until.tz_convert(timezone).strftime(
                                "%Y.%m.%d %H:%M"
                            ),
                            "예상 변화 · %": case.predicted_return * 100,
                            "실제 변화 · %": case.actual_return * 100,
                            "오차 · %p": abs(case.predicted_return - case.actual_return) * 100,
                            "범위 보정 사례": case.calibration_cases,
                        }
                        for case in result.validation
                    ]
                )
                st.dataframe(rows.round(2), hide_index=True, width="stretch")
                st.download_button(
                    "과거 예측 검증 CSV", rows.to_csv(index=False), "forecast-validation.csv", "text/csv"
                )
            else:
                st.info("이 설정으로 완료된 과거 예측 검증이 없습니다.")
            forecast_rows = pd.DataFrame(
                {
                    "data_mode": "Demo" if demo else "Live",
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframe": report.timeframe,
                    "model": MODEL_VERSION,
                    "forecast_origin_utc": report.query_end.isoformat(),
                    "future_close_utc": [date.isoformat() for date in prediction.dates],
                    "predicted_price": prediction.center,
                    "lower_price": prediction.lower,
                    "upper_price": prediction.upper,
                }
            )
            st.download_button(
                "예상 가격 경로 CSV", forecast_rows.to_csv(index=False), "forecast-prices.csv", "text/csv"
            )
            st.caption(
                "최대 최근 24회 · 현재 확보된 과거 자료 안에서 평가합니다. 거래 수익률이나 종합 신호의 백테스트 성적은 아닙니다."
            )
