"""Responsive dashboard presentation. Escape market text before rendering HTML."""

from __future__ import annotations
from typing import TYPE_CHECKING


from html import escape
from btc_analyzer.ui.browser_assets import browser_asset
from btc_analyzer.assets import price_text
import math

if TYPE_CHECKING:
    from btc_analyzer.strategy.signal_engine import Analysis
from btc_analyzer.strategy.composite import CompositeSignal, FRAME_LABELS, FRAME_WEIGHTS


CSS = "<style>" + browser_asset("theme.css") + "</style>"

BRAND = """
<div class="btc-brand">
  <div class="btc-logo" aria-hidden="true">◈</div>
  <div><h1>CRYPTO SIGNAL LAB</h1><p>코인과 선물, 가격과 근거를 함께</p></div>
  <span class="btc-brand-tag">가격 · 흐름 · 근거</span>
</div>
"""

LABELS = {
    "Strong Uptrend": "강한 상승 추세",
    "Uptrend": "상승 추세",
    "Sideways": "횡보",
    "Downtrend": "하락 추세",
    "Strong Downtrend": "강한 하락 추세",
    "Very Strong Bullish": "매우 강한 상승 우위",
    "Bullish": "상승 우위",
    "Mild Bullish": "완만한 상승 우위",
    "Neutral": "중립",
    "Mild Bearish": "완만한 하락 우위",
    "Bearish": "하락 우위",
    "Very Strong Bearish": "매우 강한 하락 우위",
    "High Quality Setup": "높은 진입 품질",
    "Valid Setup": "조건 충족",
    "Weak Setup": "추가 확인 필요",
    "Watch": "관찰 중",
    "No Trade": "관망",
    "Normal Volatility": "보통 변동성",
    "Low Volatility": "낮은 변동성",
    "High Volatility": "높은 변동성",
    "Extreme Volatility": "극단적 변동성",
    "Bullish Structure": "상승 구조",
    "Bearish Structure": "하락 구조",
    "Range": "박스권",
    "Possible Transition": "구조 전환 가능",
    "trend": "추세",
    "momentum": "모멘텀",
    "volume": "거래량",
    "volatility": "변동성",
    "structure": "시장 구조",
    "ichimoku_tenkan": "일목 · 전환선",
    "ichimoku_kijun": "일목 · 기준선",
    "ichimoku_span_a": "일목 · 선행스팬 A 계산값",
    "ichimoku_span_b": "일목 · 선행스팬 B 계산값",
    "ichimoku_cloud_a": "일목 · 현재 구름 A",
    "ichimoku_cloud_b": "일목 · 현재 구름 B",
    "ichimoku_chikou_reference": "일목 · 후행스팬 비교 종가",
    "ichimoku_cloud_position": "일목 · 구름 위치 (-1/0/1)",
    "ichimoku_tk_direction": "일목 · 전환선/기준선 방향",
    "ichimoku_chikou_direction": "일목 · 후행스팬 확인 방향",
    "ichimoku_bias": "일목 · 방향 합의 (-1~1)",
}


def korean(value: str) -> str:
    return LABELS.get(value, value)


def market_hero(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    quote: str,
    price: float,
    change: float | None,
    change_label: str,
    price_label: str,
    confirmed_at: str,
    demo: bool,
) -> str:
    """Quote units and candle/ticker labels stay explicit, including demo state."""
    badge = "DEMO · 합성 데이터" if demo else "LIVE · 공개 시장 데이터"
    badge_class = "demo" if demo else "live"
    delta = ""
    if change is not None:
        color = "up" if change >= 0 else "down"
        delta = f'<span class="btc-{color}">{change:+.2f}% · {escape(change_label)}</span>'
    return f"""
<section class="btc-hero" aria-label="시장 가격">
 <div class="btc-hero-top"><span class="btc-market">{escape(symbol)}</span>
 <span class="btc-badge">{escape(exchange)} · 현물</span><span class="btc-badge">{escape(timeframe)}</span>
 <span class="btc-badge btc-badge-{badge_class}">{badge}</span></div>
 <div class="btc-price-label">{escape(price_label)}</div>
 <div class="btc-price">{price_text(price)}<small>{escape(quote)}</small></div>
 <div class="btc-price-meta">{delta}<span>분석 기준 · {escape(confirmed_at)}</span></div>
</section>
"""


def summary_cards(analysis: Analysis) -> str:
    candidate = (
        ("매수 후보" if analysis.direction == "long" else "숏 연구 후보") if analysis.eligible else "관망"
    )
    cards = [
        (
            "상승 우위 점수",
            f"{analysis.score.overall:.1f}<small> / 100</small>",
            korean(analysis.score.label),
            analysis.score.overall,
        ),
        (
            "진입 품질",
            f"{analysis.quality:.1f}<small> / 100</small>",
            korean(analysis.quality_label),
            analysis.quality,
        ),
        ("시장 흐름", escape(korean(analysis.regime)), korean(analysis.volatility), None),
        (
            "현재 판단",
            candidate,
            "다음 봉에서 진입 조건 평가" if analysis.eligible else "조건이 갖춰질 때까지 관찰",
            None,
        ),
    ]
    rendered = []
    for label, value, hint, progress in cards:
        meter = (
            ""
            if progress is None
            else f'<div class="btc-meter"><span style="width:{max(0, min(100, progress)):.1f}%"></span></div>'
        )
        rendered.append(
            f'<div class="btc-card"><div class="btc-card-label">{label}</div><div class="btc-card-value">{value}</div><div class="btc-card-hint">{escape(hint)}</div>{meter}</div>'
        )
    return '<section class="btc-summary" aria-label="분석 요약">' + "".join(rendered) + "</section>"


def composite_cards(signal: CompositeSignal) -> str:
    """Display five-horizon judgment; data coverage is never a success probability."""
    cards = [
        ("중장기 방향", f"{signal.score.overall:.1f}<small> / 100</small>", "일봉·주봉·월봉 85%"),
        (
            "가격 매력",
            f"{signal.position.value_score:.0f}<small> / 100</small>"
            if signal.position.price is not None
            else "대기",
            f"중기 기준 대비 {signal.position.discount_pct:+.1f}% 할인"
            if signal.position.discount_pct is not None and signal.position.discount_pct >= 0
            else f"중기 기준 대비 {-signal.position.discount_pct:.1f}% 높음"
            if signal.position.discount_pct is not None
            else "계산할 이력 부족",
        ),
        (
            "하락 진정",
            f"{signal.position.stability_score:.0f}<small> / 100</small>"
            if signal.position.price is not None
            else "대기",
            "급락 진행"
            if signal.position.falling_fast
            else "지지 이탈"
            if signal.position.broken_support
            else "일봉·4시간 압력과 지지",
        ),
        (
            "지표 데이터 충족",
            f"{signal.quality:.0f}<small> %</small>",
            "데이터 범위 · 확률 아님",
        ),
    ]
    html = '<section class="btc-summary" aria-label="분석 요약">'
    for label, value, hint in cards:
        html += f'<div class="btc-card"><div class="btc-card-label">{escape(label)}</div><div class="btc-card-value">{value}</div><div class="btc-card-hint">{escape(hint)}</div></div>'
    html += '</section><section class="btc-horizons" aria-label="다섯 시간대 방향">'
    for tf, frame in signal.frames.items():
        label = "상승" if frame.score >= 60 else "하락" if frame.score <= 40 else "중립"
        color = "btc-up" if frame.score >= 60 else "btc-down" if frame.score <= 40 else ""
        value = f"{frame.score:.1f}" if frame.ready else "대기"
        status = "데이터 대기" if not frame.ready else "부분 지표" if frame.missing else "확인 완료"
        html += f'<div class="btc-horizon" title="반영 비중 {FRAME_WEIGHTS[tf]:.0%}"><span class="btc-card-label">{FRAME_LABELS[tf]}</span><strong class="{color}">{value}</strong><p>{label if frame.ready else "미반영"}</p><p>{status}</p></div>'
    return html + "</section>"


def decision_panel(signal: CompositeSignal) -> str:
    """A plain-language conclusion before technical detail, grounded in gates."""
    headings = {
        "매수": "매수 조건 충족",
        "매도": "보유분 축소 검토",
        "관망": "신규 매수 대기",
    }
    if signal.mode == "눌림목 분할매수":
        headings["매수"] = "눌림목 분할매수 검토"
        reason = "가격 할인과 하락 압력 둔화를 확인했습니다. 주봉·월봉 방향, 일봉 변동성, 비용 후 손익비를 충족하여 단기 상승 전에도 분할매수를 검토할 수 있습니다."
    elif signal.action == "매수":
        reason = "일봉·주봉·월봉이 상승 방향을 지지합니다. 일봉 변동성과 수수료·슬리피지를 반영한 손익비가 매수 기준을 충족했습니다."
    elif signal.mode == "과열 분할매도":
        headings["매도"] = "과열 구간 · 분할 이익 실현 검토"
        reason = "일봉 RSI와 중기 기준 대비 가격 이격이 과열 기준에 도달했습니다. 현물 보유자는 분할 이익 실현을 검토할 수 있습니다."
    elif signal.action == "매도":
        reason = "일봉·주봉의 하락 방향이 일치합니다. 현물 보유자는 보유분 축소를 검토할 수 있습니다."
    elif signal.ready_frames < 5:
        reason = f"5개 중 {signal.ready_frames}개 시간대만 준비되었습니다. 최신 확정 자료가 모두 준비될 때까지 판단을 보류합니다."
    elif any("극단적 변동성" in item for item in signal.reasons):
        reason = "급락 또는 높은 변동성으로 신규 매수를 보류합니다. 가격 안정 확인이 필요합니다."
    elif signal.position.broken_support:
        reason = "확정 일봉 지지를 이탈했습니다. 신규 매수 전 하락 진정과 지지 회복을 확인해야 합니다."
    elif any("0.6배" in item for item in signal.reasons):
        reason = "일봉·4시간봉 거래량이 부족하여 신규 매수를 보류합니다."
    elif any("RR 조건이 부족" in item for item in signal.reasons):
        reason = "수수료·슬리피지를 반영한 손익비가 기준에 미달합니다. 진입가격과 일봉 지지를 다시 확인해야 합니다."
    elif signal.position.value_score >= 65:
        reason = "중기 기준보다 낮은 가격이지만 매수 조건이 모두 충족되지는 않았습니다. 장기 지지와 하락 진정을 확인한 후 분할매수를 검토합니다."
    else:
        supported = (
            signal.frames["1w"].score >= 48
            and signal.frames["1M"].score >= 45
            and signal.position.macro_score >= 50
        )
        reason = (
            "주봉·월봉 지지는 유지되고 있습니다. 가격 할인과 하락 진정 조건을 함께 확인한 후 분할매수를 검토합니다."
            if supported
            else "주봉·월봉의 상승 지지가 부족합니다. 장기 방향 회복을 확인할 때까지 신규 매수를 보류합니다."
        )
    kind = {"매수": "buy", "매도": "sell", "관망": "hold"}[signal.action]
    return f'<section class="btc-signal btc-signal-{kind} notranslate" lang="ko" translate="no" aria-label="종합 신호 근거"><span class="btc-signal-label">{signal.action} · 종합 신호 · {escape(signal.mode)}</span><h2>{headings[signal.action]}</h2><p>{escape(reason)}</p>{buy_watch_card(signal)}</section>'


def buy_watch_card(signal: CompositeSignal) -> str:
    watch = signal.buy_watch
    if signal.action != "관망" or watch is None:
        return ""
    title = "<span>매수 검토 가격대</span>"
    if watch.low is None:
        return f'<div class="btc-buy-watch notranslate" lang="ko" translate="no" aria-label="매수 검토 가격 보류">{title}<p>{escape(watch.reason)}</p></div>'
    import pandas as pd

    as_of = pd.Timestamp(watch.as_of).tz_convert("Asia/Seoul").strftime("%m.%d %H:%M")
    return (
        '<div class="btc-buy-watch notranslate" lang="ko" translate="no" id="btc-buy-watch" aria-label="조건부 매수 검토 가격대" '
        f'data-low="{watch.low}" data-high="{watch.high}" data-stop="{watch.invalidation}" '
        f'data-risk-floor="{watch.risk_floor}" '
        f'data-base-at="{pd.Timestamp(watch.as_of).timestamp() * 1000:.0f}" '
        f'data-expires="{pd.Timestamp(watch.valid_until).timestamp() * 1000:.0f}" data-status="waiting">'
        f'{title}<b class="btc-buy-watch-price">{price_text(watch.low)} ~ {price_text(watch.high)} USDT</b>'
        '<p class="btc-buy-watch-distance">실시간 시세 확인 대기 · 현재가와 검토 가격대의 차이를 표시합니다.</p>'
        f"<p>{escape(watch.reason)}</p>"
        "<p>이 가격대에서 분할매수를 검토할 수 있습니다. 진입 전 하락 진정과 주봉·월봉 지지를 확인해야 합니다.</p>"
        f"<small>회복 비교 기준 {price_text(watch.target)} · 지지 재평가 {price_text(watch.invalidation)} USDT · 이탈 시 보류</small>"
        f"<small>{as_of} KST 확정 봉 기준 · 조건부 검토 가격이며 예상 도착 가격이나 자동 매수 신호가 아닙니다.</small></div>"
    )


def ichimoku_cards(values: dict, displacement: int = 26) -> str:
    """Translate current, causal Ichimoku evidence into three understandable checks."""

    def label(key: str, up: str, down: str, middle: str) -> str:
        value = values.get(key)
        return (
            "이력 부족"
            if value is None or not math.isfinite(float(value))
            else up
            if value > 0
            else down
            if value < 0
            else middle
        )

    items = [
        (
            "가격과 구름",
            label("ichimoku_cloud_position", "구름 위", "구름 아래", "구름 안"),
            "구름 위는 상승, 아래는 하락 방향의 근거예요.",
        ),
        (
            "전환선과 기준선",
            label("ichimoku_tk_direction", "전환선 우위", "기준선 우위", "두 선이 같음"),
            "빠른 흐름과 중기 흐름이 같은 방향인지 봐요.",
        ),
        (
            "후행스팬 확인",
            label(
                "ichimoku_chikou_direction", "과거 종가보다 높음", "과거 종가보다 낮음", "과거 종가와 같음"
            ),
            f"현재 종가를 {displacement}봉 전 종가와 비교해요.",
        ),
    ]
    result = '<section class="btc-ichimoku" aria-label="일목균형표 해석">'
    for title, value, hint in items:
        result += f'<article><span class="btc-card-label">{escape(title)}</span><strong>{escape(value)}</strong><p>{escape(hint)}</p></article>'
    return result + "</section>"
