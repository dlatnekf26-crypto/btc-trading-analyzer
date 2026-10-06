"""Plain-language indicator states; reuse features and isolate local UI reruns."""

from dataclasses import dataclass
from html import escape
import math

import pandas as pd
import streamlit as st

from btc_analyzer.candles import candle_close
from btc_analyzer.config import COMPOSITE_TIMEFRAMES, IndicatorConfig
from btc_analyzer.strategy.composite import FRAME_LABELS
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS
from btc_analyzer.ui.charts import READ_CHART_CONFIG, indicator_chart


@dataclass(frozen=True)
class IndicatorCard:
    label: str
    state: str = "자료 부족"
    value: str = "—"
    meaning: str = "확정 봉 이력이 더 필요해요."
    tone: str = "neutral"


def number(row, key):
    value = row.get(key)
    try:
        return float(value) if math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def indicator_cards(features: pd.DataFrame, cfg: IndicatorConfig) -> list[IndicatorCard]:
    """Interpret the latest row only; never backfill a missing current value."""
    row = features.iloc[-1] if not features.empty else {}
    cards = []
    fast, slow = number(row, "ema_20"), number(row, "ema_50")
    card = IndicatorCard("추세 · EMA20/50")
    if fast is not None and slow is not None and fast > 0 and slow > 0:
        state, tone = ("단기 평균이 위", "up") if fast > slow else ("단기 평균이 아래", "down")
        if fast == slow:
            state, tone = "두 평균이 같음", "neutral"
        card = IndicatorCard(
            card.label, state, f"{(fast / slow - 1) * 100:+.1f}%", "20봉 평균과 50봉 평균의 차이예요.", tone
        )
    cards.append(card)
    value = number(row, "rsi")
    card = IndicatorCard("매수·매도 힘 · RSI")
    if value is not None and 0 <= value <= 100:
        state, tone = ("매수 힘 우위", "up") if value > 50 else ("매도 힘 우위", "down")
        if value >= 70:
            state, tone = "매수 과열 구간", "caution"
        elif value <= 30:
            state, tone = "매도 과열 구간", "caution"
        elif round(value, 1) == 50:
            # Match the displayed precision around equilibrium; 50.0 should
            # not appear to contradict a directional strength label.
            state, tone = "힘의 균형", "neutral"
        card = IndicatorCard(
            card.label,
            state,
            f"{value:.1f} / 100",
            "30 이하 매도 과열 · 70 이상 매수 과열. 반전 확정은 아니에요.",
            tone,
        )
    cards.append(card)
    line, signal = number(row, "macd"), number(row, "macd_signal")
    card = IndicatorCard("추세 탄력 · MACD")
    if line is not None and signal is not None:
        state, tone = ("기준선 위", "up") if line > signal else ("기준선 아래", "down")
        if line == signal:
            state, tone = "기준선과 같음", "neutral"
        zero = "0 위예요" if line > 0 else "0 아래예요" if line < 0 else "0과 같아요"
        card = IndicatorCard(
            card.label,
            state,
            f"{line - signal:+,.2f} USDT",
            f"MACD − 기준선 차이 · MACD 자체는 {zero}.",
            tone,
        )
    cards.append(card)
    value = number(row, "atr_pct")
    card = IndicatorCard("평균 변동 폭 · ATR")
    if value is not None and value >= 0:
        reference = features.get("atr_pct", pd.Series(dtype=float)).tail(20)
        reference = reference[reference.map(lambda x: pd.notna(x) and math.isfinite(x) and x >= 0)]
        typical = float(reference.median()) if len(reference) >= 10 else None
        state, tone = "변동 폭 확인", "neutral"
        if typical is not None and typical > 0:
            state = (
                "평소보다 큼"
                if value >= typical * 1.25
                else "평소보다 작음"
                if value <= typical * 0.75
                else "평소 수준"
            )
            tone = "caution" if state == "평소보다 큼" else "neutral"
        card = IndicatorCard(
            card.label,
            state,
            f"{value:.2f}%",
            f"최근 {cfg.atr_length}봉 평균 진폭 / 종가. 평소는 최근 20봉 중앙값 기준이에요.",
            tone,
        )
    cards.append(card)
    value = number(row, "volume_ratio")
    card = IndicatorCard("거래 참여 · 거래량")
    if value is not None and value >= 0:
        state = "거래가 활발함" if value >= 1.5 else "거래가 뜸함" if value < 0.7 else "평균 수준"
        card = IndicatorCard(
            card.label,
            state,
            f"{value:.2f}배",
            f"최근 {cfg.volume_length}봉 평균 대비. 거래량만으로 방향을 정하지 않아요.",
            "up" if value >= 1.5 else "neutral",
        )
    cards.append(card)
    close, cloud_a, cloud_b = (number(row, key) for key in ("close", "ichimoku_cloud_a", "ichimoku_cloud_b"))
    card = IndicatorCard("추세 위치 · 일목균형표")
    if all(value is not None and value > 0 for value in (close, cloud_a, cloud_b)):
        state, tone = ("구름 위", "up") if close > max(cloud_a, cloud_b) else ("구름 아래", "down")
        if min(cloud_a, cloud_b) <= close <= max(cloud_a, cloud_b):
            state, tone = "구름 안", "neutral"
        card = IndicatorCard(
            card.label, state, f"{close:,.2f} USDT", "현재 구름과 확정 종가의 위치를 비교해요.", tone
        )
    cards.append(card)
    return cards


def cards_html(cards: list[IndicatorCard]) -> str:
    articles = []
    for card in cards:
        articles.append(
            f'<article class="btc-indicator-card btc-indicator-{escape(card.tone)}">'
            f'<div class="btc-indicator-label">{escape(card.label)}</div>'
            f'<strong>{escape(card.state)}</strong><div class="btc-indicator-value">{escape(card.value)}</div>'
            f"<p>{escape(card.meaning)}</p></article>"
        )
    return (
        '<section class="btc-indicator-grid" aria-label="기술지표 현재 상태">'
        + "".join(articles)
        + "</section>"
    )


CHARTS = {"RSI": "매수·매도 힘", "MACD": "추세 탄력", "ATR": "변동 폭", "BB": "밴드 폭", "VOLUME": "거래량"}
GUIDES = {
    "RSI": (
        "RSI · 매수와 매도, 어느 쪽 힘이 셀까요?",
        "파란 선이 50 위면 매수 힘 우위 · 분홍 구간 70~100, 파란 구간 0~30은 과열 구간이에요.",
    ),
    "MACD": (
        "MACD · 최근 흐름이 기준선보다 강할까요?",
        "파란 선이 주황 기준선 위면 초록 막대, 아래면 빨간 막대예요. 막대는 두 선의 차이예요.",
    ),
    "ATR": (
        "ATR · 한 봉의 변동 폭은 어느 정도일까요?",
        "가격 대비 평균 진폭이에요. 높을수록 흔들림이 크며, 상승·하락 방향을 뜻하지 않아요.",
    ),
    "BB": (
        "볼린저밴드 · 가격의 퍼짐이 커졌을까요?",
        "밴드 폭 / 중심선의 비율이에요. 높으면 가격이 넓게 퍼지고 낮으면 좁게 모여요.",
    ),
    "VOLUME": (
        "거래량 · 평소보다 거래가 많을까요?",
        "점선 1배가 최근 평균이에요. 선이 점선 위면 평균보다 거래량이 많아요.",
    ),
}


@st.cache_data(ttl=3600, max_entries=32, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def indicator_chart_spec(features, timezone, kind):
    return indicator_chart(features, timezone, kind).to_dict()


@st.fragment
def render_indicators(enriched, cfg, timezone):
    st.subheader("기술지표 한눈에 보기")
    selected = (
        st.segmented_control(
            "지표 시간대",
            COMPOSITE_TIMEFRAMES,
            default="1d",
            format_func=FRAME_LABELS.get,
            key="indicator_timeframe",
        )
        or "1d"
    )
    features = enriched.get(selected)
    if features is None or features.empty:
        st.info("이 시간대의 확정 봉이 아직 없습니다.")
        return
    confirmed = candle_close(features.index[-1], selected).tz_convert(timezone)
    st.caption(f"{FRAME_LABELS[selected]} · 확정 봉 마감 {confirmed:%Y.%m.%d %H:%M} KST · Binance BTC/USDT")
    st.markdown(cards_html(indicator_cards(features, cfg)), unsafe_allow_html=True)
    st.caption("각 지표의 현재 상태예요. 종합 매수·매도 판단은 화면 위의 다중 시간대 신호를 함께 확인하세요.")
    kind = (
        st.segmented_control(
            "자세히 볼 지표", list(CHARTS), default="RSI", format_func=CHARTS.get, key="indicator_kind"
        )
        or "RSI"
    )
    title, guide = GUIDES[kind]
    st.markdown(f"**{title}**")
    st.caption(guide)
    visible = features.tail(120).copy(deep=False)
    visible.attrs = {**features.attrs, "timeframe": selected}
    st.plotly_chart(
        indicator_chart_spec(visible, timezone, kind),
        width="stretch",
        theme=None,
        config=READ_CHART_CONFIG,
        key="indicator_focus_chart",
    )
    st.caption("최근 120개 확정 봉 · 손가락을 대거나 마우스를 올리면 시각과 값이 보여요.")
    with st.expander("다른 지표의 현재값", key="indicator_values", on_change="rerun") as details:
        if details.open:
            row = features.iloc[-1]
            values = []
            for key, label in [
                *((f"ema_{period}", f"지수 이동평균 · {period}봉") for period in cfg.ema_lengths),
                *((f"sma_{period}", f"단순 이동평균 · {period}봉") for period in cfg.sma_lengths),
                ("bb_upper", "볼린저밴드 · 상단"),
                ("bb_middle", "볼린저밴드 · 중심"),
                ("bb_lower", "볼린저밴드 · 하단"),
                ("ichimoku_tenkan", "일목 · 전환선"),
                ("ichimoku_kijun", "일목 · 기준선"),
            ]:
                value = number(row, key)
                values.append(
                    {"지표": label, "현재값 · USDT": f"{value:,.2f}" if value is not None else "자료 부족"}
                )
            st.dataframe(pd.DataFrame(values), hide_index=True, width="stretch")
