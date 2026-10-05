"""Lazy public history, forecasts and distinct retrospective comparison views."""

import sqlite3

import numpy as np
import pandas as pd
import streamlit as st

from btc_analyzer.analysis.historical_similarity import (
    FORWARD_OPTIONS,
    HISTORY_BARS,
    WINDOW_OPTIONS,
    SimilarityReport,
    find_similar_history,
)
from btc_analyzer.candles import candle_boundary, candle_close, candle_shift
from btc_analyzer.config import COMPOSITE_TIMEFRAMES, TIMEFRAMES
from btc_analyzer.data.base_provider import DataError, utc
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.analysis.forecast import predict_history
from btc_analyzer.ui.forecast_view import render_prediction
from btc_analyzer.strategy.composite import FRAME_LABELS


def duration_label(timeframe: str, bars: int) -> str:
    if timeframe == "1M":
        return f"{bars}개월"
    if timeframe == "1w":
        return f"{bars}주"
    hours = TIMEFRAMES[timeframe] * bars // 3600
    return f"{hours // 24}일" if hours % 24 == 0 else f"{hours}시간"


def fetch_history(cache_path: str, exchange: str, symbol: str, timeframe: str, end: str, *, refresh=False):
    boundary = candle_boundary(utc(end), timeframe)
    try:
        return {
            "frame": DataService(cache_path).history(
                exchange, symbol, timeframe, boundary, HISTORY_BARS[timeframe], refresh=refresh
            )
        }
    except (DataError, ValueError, OSError, sqlite3.Error) as exc:
        return {"error": str(exc)}


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def public_history(cache_path: str, exchange: str, symbol: str, timeframe: str, end: str, _refresh=False):
    # Clear this key before a forced refresh. Ignoring _refresh in the hash
    # stores the newly fetched result under the ordinary key, including errors.
    # Persistent OHLCV caching also avoids API paging between control changes.
    return fetch_history(cache_path, exchange, symbol, timeframe, end, refresh=_refresh)


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False)
def history_comparison(
    frame: pd.DataFrame, timeframe: str, end: str, window: int, forward: int, minimum: int
):
    return find_similar_history(frame, timeframe, end, window, forward, min_similarity=minimum)


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False)
def forecast_analysis(frame, timeframe, end, window, forward, minimum):
    return predict_history(frame, timeframe, end, window, forward, min_similarity=minimum)


@st.cache_data(ttl=3600, max_entries=5, show_spinner=False)
def demo_history(research_timeframe, bars, price, timeframe):
    return demo_bundle(
        research_timeframe,
        bars,
        price=price,
        include_macro=True,
        history_limits={timeframe: HISTORY_BARS[timeframe]},
        only_timeframe=timeframe,
    )[timeframe]


def comparison_chart(report: SimilarityReport, timezone: str):
    import plotly.graph_objects as go

    from btc_analyzer.ui.charts import style_chart

    fig = go.Figure()
    before = list(range(1 - report.window, 1))
    colors = ("#36a994", "#9472d9", "#e49d42", "#da7187", "#8092ad")

    def dates(start, count):
        return [
            candle_shift(start, report.timeframe, i + 1).tz_convert(timezone).strftime("%Y.%m.%d %H:%M")
            for i in range(count)
        ]

    for number, match in enumerate(report.matches):
        color = colors[number % len(colors)]
        label = f"{match.start.tz_convert(timezone):%Y.%m.%d} · {match.similarity:.0f}점"
        actual_dates = dates(match.start, len(match.path))
        fig.add_trace(
            go.Scatter(
                x=before,
                y=match.path[: report.window],
                customdata=actual_dates[: report.window],
                name=label,
                legendgroup=str(number),
                mode="lines",
                line={"color": color, "width": 1.7},
                hovertemplate="%{customdata}<br>비교 가격 %{y:.2f}<extra>%{fullData.name}</extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=list(range(report.forward + 1)),
                y=match.path[report.window - 1 :],
                customdata=actual_dates[report.window - 1 :],
                name=label + " · 이후 실제 가격",
                legendgroup=str(number),
                showlegend=False,
                mode="lines",
                line={"color": color, "width": 1.7, "dash": "dot"},
                hovertemplate="%{customdata}<br>당시 이후 실제 가격 %{y:.2f}<extra>%{fullData.name}</extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=before,
            y=report.current_path,
            customdata=dates(report.query_start, report.window),
            name="지금 비교하는 차트",
            mode="lines",
            line={"color": "#3182f6", "width": 4},
            hovertemplate="%{customdata}<br>비교 가격 %{y:.2f}<extra>지금 비교하는 차트</extra>",
        )
    )
    fig.add_vrect(x0=0, x1=report.forward, fillcolor="#3182f6", opacity=0.045, line_width=0, layer="below")
    fig.add_vline(x=0, line_dash="dash", line_color="#aab5c5")
    style_chart(fig, height=460)
    # Wrapped legends remain above the plot on a narrow phone screen.
    fig.update_layout(
        legend={"y": 1.02, "yanchor": "bottom"},
        margin={"t": 85},
        uirevision=f"history-{report.timeframe}-{report.window}-{report.forward}",
    )
    fig.update_xaxes(title="비교 시점 이전 ← 봉 수 → 당시 이후", range=[1 - report.window, report.forward])
    fig.update_yaxes(title="각 구간 마지막 종가 = 100", tickformat=".1f")
    return fig


@st.fragment
def render_history_view(
    *,
    cache_path: str,
    exchange: str,
    symbol: str,
    cutoff,
    demo: bool,
    demo_frames: dict,
    timezone: str,
    refresh: bool = False,
    research_timeframe: str = "1d",
    demo_bars: int = 800,
    demo_price: float = 90_000,
    live_deadline=None,
):
    st.subheader("다음 흐름, 범위까지 함께 봐요")
    st.write("닮았던 과거로 예상 가격 경로를 계산하고, 과거 예측 오차까지 확인해요.")
    mode = (
        st.segmented_control(
            "분석 보기", ["예측 경로", "과거 비교"], default="예측 경로", key="prediction_mode"
        )
        or "예측 경로"
    )
    if "similarity_timeframe" not in st.session_state:
        st.session_state["similarity_timeframe"] = st.session_state.get("price_chart_timeframe", "1d")
    tf = (
        st.segmented_control(
            "비교 시간대",
            COMPOSITE_TIMEFRAMES,
            format_func=FRAME_LABELS.get,
            key="similarity_timeframe",
        )
        or "1d"
    )
    with st.expander("기간 · 비교 설정"):
        left, right = st.columns(2)
        window = left.select_slider(
            "최근 비교 구간",
            WINDOW_OPTIONS[tf],
            value=WINDOW_OPTIONS[tf][1],
            format_func=lambda count: f"{duration_label(tf, count)} · {count}봉",
            key=f"similarity_window_{tf}",
        )
        forward = right.select_slider(
            "예측 기간",
            FORWARD_OPTIONS[tf],
            value=FORWARD_OPTIONS[tf][1],
            format_func=lambda count: duration_label(tf, count),
            key=f"similarity_forward_{tf}",
        )
        with st.expander("비교 기준"):
            minimum = st.select_slider("최소 유사도 · 점", (50, 60, 70, 80), value=60)
            st.write(
                "가격 경로 65% · 수익률 변동성 20% · 상대 거래량 15%를 비교해요. 가격과 거래량의 절대 규모 차이는 정규화합니다."
            )
            st.caption(
                "유사도는 0~100점의 닮은 정도이며 상승 확률이 아니에요. 이후 수익률로 사례를 고르지 않고, 서로 겹치는 구간도 제외해요."
            )
    st.caption(
        f"최근 {duration_label(tf, window)} 비교 → 앞으로 {duration_label(tf, forward)} 예상 · 최소 유사도 {minimum}점"
    )
    refresh_sequence = st.session_state.get("market_refresh_sequence", 0)
    forced = st.button("비교 자료 새로고침") or (
        refresh and st.session_state.get("_history_refresh_consumed", -1) != refresh_sequence
    )
    if refresh:
        st.session_state["_history_refresh_consumed"] = refresh_sequence
    if not demo and live_deadline is not None:
        cutoff = min(utc(live_deadline), pd.Timestamp.now(tz="UTC"))
    boundary = candle_boundary(utc(cutoff), tf).isoformat()
    with st.spinner("과거 확정 봉에서 비슷한 흐름을 찾는 중…"):
        if demo:
            # Keep the exact dashboard path, including a 5m research base.
            frame = demo_history(research_timeframe, demo_bars, demo_price, tf)
            original = demo_frames.get(tf)
            if original is not None and not original.empty:
                # Demo has a fixed end; preserve the dashboard query exactly.
                common = frame.index.intersection(original.index)
                if not frame.loc[common].equals(original.loc[common]):
                    st.error("합성 차트의 가격 경로가 일치하지 않습니다.")
                    return
        else:
            args = (cache_path, exchange, symbol, tf, boundary)
            if forced:
                public_history.clear(*args)
            response = public_history(*args, _refresh=forced)
            if "error" in response:
                st.error(f"과거 비교 자료를 받지 못했습니다: {response['error']}")
                st.caption(
                    "현재 시장의 실제 데이터를 받아야 비교할 수 있어요. 잠시 후 ‘비교 자료 새로고침’을 눌러 주세요."
                )
                return
            frame = response["frame"]
        try:
            result = forecast_analysis(frame, tf, boundary, window, forward, minimum)
            report = result.history
        except ValueError as exc:
            st.info(str(exc))
            return
    if demo:
        st.warning("DEMO · 유사 구간도 같은 합성 가격 경로에서 찾은 결과입니다.")

    def stamp(value):
        return value.tz_convert(timezone).strftime("%Y.%m.%d %H:%M")

    source = "합성 자료" if demo else f"{exchange} 공개 시세 API"
    st.caption(
        f"자료: {source} · {symbol} · {FRAME_LABELS[tf]} · {stamp(report.history_start)} ~ {stamp(report.history_end)} · {report.candidate_count:,}개 과거 구간 비교"
    )
    st.caption(f"최근 비교 구간: {stamp(report.query_start)} ~ {stamp(report.query_end)} · {timezone}")
    if not report.volume_used:
        st.info("최근 거래량이 0이어서 가격·변동성만 비교했습니다.")
    if not report.matches:
        st.info("조건에 맞는 유사 구간이 없습니다. 비교 구간이나 최소 유사도를 조정해 보세요.")
        if report.best_similarity is not None:
            st.caption(
                f"가장 가까운 과거도 {report.best_similarity:.1f}점으로 기준 {minimum}점에 못 미쳤어요."
            )
        else:
            st.caption("최근 구간보다 앞에서 이후 관찰까지 끝난 연속 데이터가 부족합니다.")
        return
    closest = report.matches[0]
    st.success(
        f"가장 닮은 과거는 {stamp(closest.start)} ~ {stamp(candle_close(closest.end, tf))} · 유사도 {closest.similarity:.1f}점이에요."
    )
    period = duration_label(tf, forward)
    quote = symbol.split("/")[-1] if exchange == "Binance" else symbol.split("-")[0]
    if mode == "예측 경로":
        render_prediction(result, timezone, quote, period, demo=demo, exchange=exchange, symbol=symbol)
    else:
        outcomes = np.array([match.forward_return for match in report.matches])
        a, b, c = st.columns(3)
        a.metric("비슷한 과거", f"{len(outcomes)}개")
        b.metric(f"당시 {period} 뒤 중앙값", f"{np.median(outcomes):+.1%}")
        c.metric(f"당시 {period} 뒤 상승", f"{int((outcomes > 0).sum())} / {len(outcomes)}개")
        st.caption(
            f"선택한 사례의 {period} 뒤 종가 변화: {outcomes.min():+.1%} ~ {outcomes.max():+.1%}. 수수료·체결을 적용한 전략 수익률은 아니에요."
        )
        if len(outcomes) < 3:
            st.info("비슷한 사례가 3개 미만이에요. 소수 사례의 결과만으로 방향을 판단하기 어렵습니다.")
        st.plotly_chart(
            comparison_chart(report, timezone),
            width="stretch",
            key="historical_similarity_chart",
            theme=None,
            config={"displaylogo": False, "displayModeBar": False},
        )
        st.caption(
            "파란 실선은 최근 차트, 색 실선은 닮았던 과거예요. 오른쪽 점선은 그때 이후 실제 가격이며 현재 차트의 예측선이 아닙니다."
        )
        st.caption(
            "가격 수준이 달라도 비교할 수 있게 각 구간 마지막 종가를 100으로 맞췄어요. 같은 흐름이 반복된다는 보장은 없습니다."
        )
        rows = pd.DataFrame(
            [
                {
                    "비슷했던 시기": f"{stamp(match.start)} ~ {stamp(candle_close(match.end, tf))}",
                    "유사도 · 점": match.similarity,
                    f"{period} 뒤 · %": match.forward_return * 100,
                    "그사이 최대 하락 · %": match.lowest_return * 100,
                }
                for match in report.matches
            ]
        )
        st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            column_config={name: st.column_config.NumberColumn(format="%.1f") for name in rows.columns[1:]},
        )
    downloads = st.expander("세부 유사도 · 비교 자료 다운로드", key="history_downloads", on_change="rerun")
    if not downloads.open:
        return
    with downloads:
        details = pd.DataFrame(
            [
                {
                    "data_mode": "Demo" if demo else "Live",
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframe": tf,
                    "window_bars": window,
                    "forward_bars": forward,
                    "query_start_utc": report.query_start.isoformat(),
                    "query_end_utc": report.query_end.isoformat(),
                    "match_start_utc": match.start.isoformat(),
                    "match_end_utc": candle_close(match.end, tf).isoformat(),
                    "observed_until_utc": match.observed_until.isoformat(),
                    "similarity": match.similarity,
                    "price_similarity": match.price_similarity,
                    "volatility_similarity": match.volatility_similarity,
                    "volume_similarity": match.volume_similarity,
                    "forward_return_pct": match.forward_return * 100,
                    "lowest_return_pct": match.lowest_return * 100,
                    "highest_return_pct": match.highest_return * 100,
                }
                for match in report.matches
            ]
        )
        st.dataframe(
            details[["match_start_utc", "price_similarity", "volatility_similarity", "volume_similarity"]]
            .rename(
                columns={
                    "match_start_utc": "과거 시작 · UTC",
                    "price_similarity": "가격 경로 · 점",
                    "volatility_similarity": "변동성 · 점",
                    "volume_similarity": "거래량 · 점",
                }
            )
            .round(1),
            hide_index=True,
            width="stretch",
        )
        st.download_button(
            "유사 구간 CSV", details.to_csv(index=False), "historical-similarity.csv", "text/csv"
        )
        candles = frame.loc[
            (frame.index >= report.history_start) & (candle_close(frame.index, tf) <= report.history_end)
        ].copy()
        candles.index.name = "open_time_utc"
        candles["data_mode"] = "Demo" if demo else "Live"
        candles["exchange"], candles["symbol"], candles["timeframe"] = exchange, symbol, tf
        st.download_button("비교 가격·거래량 CSV", candles.to_csv(), "historical-candles.csv", "text/csv")
