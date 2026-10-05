"""Lazy public history, forecasts and distinct retrospective comparison views."""

import sqlite3

import pandas as pd
import streamlit as st

from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

from btc_analyzer.analysis.historical_similarity import (
    FORWARD_OPTIONS,
    HISTORY_BARS,
    WINDOW_OPTIONS,
    find_similar_history,
)
from btc_analyzer.candles import candle_boundary, candle_close
from btc_analyzer.config import COMPOSITE_TIMEFRAMES, TIMEFRAMES
from btc_analyzer.data.base_provider import DataError, utc
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.analysis.forecast import HORIZON_LABELS, horizon_days, predict_history
from btc_analyzer.ui.forecast_view import render_prediction
from btc_analyzer.ui.similarity_view import render_comparison
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


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def history_comparison(
    frame: pd.DataFrame, timeframe: str, end: str, window: int, forward: int, minimum: int
):
    return find_similar_history(frame, timeframe, end, window, forward, min_similarity=minimum)


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
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
    st.subheader("기간별 가격 전망")
    st.write("예상 가격과 닮았던 과거를 함께 확인하세요.")
    mode = (
        st.segmented_control(
            "분석 보기",
            ["예측 경로", "과거 비교"],
            default="예측 경로",
            key="prediction_mode",
            label_visibility="collapsed",
        )
        or "예측 경로"
    )
    if st.session_state.get("forecast_horizon") == "1y":
        st.session_state["forecast_horizon"] = "3mo"
    horizon = (
        st.segmented_control(
            "예측 기간",
            [*HORIZON_LABELS, "custom"],
            default="1mo",
            format_func=lambda value: HORIZON_LABELS.get(value, "직접 설정"),
            key="forecast_horizon",
        )
        or "1mo"
    )
    if not demo and live_deadline is not None:
        cutoff = min(utc(live_deadline), pd.Timestamp.now(tz="UTC"))
    tf = "1d"
    with st.expander("비교 조건 · 새로고침", expanded=horizon == "custom"):
        if horizon == "custom":
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
        window = st.select_slider(
            "최근 비교 구간",
            WINDOW_OPTIONS[tf],
            value=WINDOW_OPTIONS[tf][1],
            format_func=lambda count: f"{duration_label(tf, count)} · {count}봉",
            key=f"similarity_window_{tf}",
        )
        if horizon == "custom":
            forward = st.select_slider(
                "이후 관찰할 봉 수",
                FORWARD_OPTIONS[tf],
                value=FORWARD_OPTIONS[tf][1],
                format_func=lambda count: duration_label(tf, count),
                key=f"similarity_forward_{tf}",
            )
        else:
            forward = horizon_days(candle_boundary(utc(cutoff), "1d"), horizon)
        minimum = st.select_slider("최소 유사도 · 점", (50, 60, 70, 80), value=60)
        st.caption(
            "가격 경로·변동성·상대 거래량을 비교합니다. RSI·ADX·CMF는 예측 근거에서 참고 지표로 확인할 수 있어요. 이후 결과로 사례를 고르지 않으며 서로 겹치는 기간을 제외합니다. 유사도는 상승 확률이 아니에요."
        )
        manual_refresh = st.button("비교 자료 새로고침")
    period = HORIZON_LABELS.get(horizon, duration_label(tf, forward))
    st.caption(f"{FRAME_LABELS[tf]} · 최근 {duration_label(tf, window)} 패턴 → {period} 뒤 전망")
    refresh_sequence = st.session_state.get("market_refresh_sequence", 0)
    forced = manual_refresh or (
        (refresh or refresh_sequence > 0)
        and st.session_state.get("_history_refresh_consumed", -1) != refresh_sequence
    )
    st.session_state["_history_refresh_consumed"] = refresh_sequence
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
            if mode == "예측 경로":
                result = forecast_analysis(frame, tf, boundary, window, forward, minimum)
                report = result.history
            else:
                # A retrospective chart needs no future-path calibration or validation.
                report = history_comparison(frame, tf, boundary, window, forward, minimum)
        except ValueError as exc:
            st.info(str(exc))
            return
    if demo:
        st.warning("DEMO · 유사 구간과 예측은 합성 가격 기준입니다.")

    def stamp(value):
        return value.tz_convert(timezone).strftime("%Y.%m.%d %H:%M")

    source = "합성 자료" if demo else f"{exchange} 공개 시세 API"
    st.caption(
        f"자료: {source} · {symbol} · {FRAME_LABELS[tf]} · {stamp(report.query_end)} 기준 · {timezone}"
    )
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
    quote = symbol.split("/")[-1] if exchange == "Binance" else symbol.split("-")[0]
    if mode == "예측 경로":
        render_prediction(
            result, timezone, quote, period, demo=demo, exchange=exchange, symbol=symbol, context_frame=frame
        )
    else:
        render_comparison(report, timezone, duration_label(tf, forward))
    downloads = st.expander("세부 유사도 · 비교 자료 다운로드", key="history_downloads", on_change="rerun")
    if not downloads.open:
        return
    with downloads:
        st.caption(
            f"수집 범위: {stamp(report.history_start)} ~ {stamp(report.history_end)} · {report.candidate_count:,}개 과거 구간 비교"
        )
        st.caption(f"최근 비교 구간: {stamp(report.query_start)} ~ {stamp(report.query_end)} · {timezone}")
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
                    "context_similarity": match.context_similarity,
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
