"""Plain-language indicator states; reuse features and isolate local UI reruns."""

from dataclasses import dataclass
from html import escape
from btc_analyzer.assets import price_text
import math

import pandas as pd

from btc_analyzer.config import IndicatorConfig


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
            f"{price_text(line - signal, signed=True)} USDT",
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
            card.label, state, f"{price_text(close)} USDT", "현재 구름과 확정 종가의 위치를 비교해요.", tone
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
