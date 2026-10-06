"""Responsive dashboard presentation. Escape market text before rendering HTML."""

from __future__ import annotations
from typing import TYPE_CHECKING


from html import escape
import math

if TYPE_CHECKING:
    from btc_analyzer.strategy.signal_engine import Analysis
from btc_analyzer.strategy.composite import CompositeSignal, FRAME_LABELS, FRAME_WEIGHTS


CSS = """
<style>
:root { --btc-muted: #66758b; --btc-line: #e7ecf3; --btc-blue: #3182f6; }
.stApp { background: #f5f7fb; color: #191f28; }
html, body, [class*="css"], .stApp {
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Pretendard', 'Segoe UI', sans-serif;
}
[data-testid="stHeader"] { background: rgba(245, 247, 251, .94); }
.block-container { max-width: 1440px; padding: 4.5rem 2rem 3rem; }
[data-testid="stSidebar"] { background: #fff; border-right: 1px solid #e7ecf3; }
[data-testid="stSidebar"] .block-container { padding: 1rem; }
h1, h2, h3 { letter-spacing: -.045em; color: #191f28; }
p, li { line-height: 1.7; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #66758b; }
[data-testid="stMetric"] {
    background: #fff; padding: 16px; border: 1px solid #e7ecf3; border-radius: 18px;
}
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; font-size: 1.8rem; }
[data-testid="stMetricLabel"] { color: #66758b; }
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
    border-radius: 12px; min-height: 44px; font-weight: 600;
}
[data-testid="stButtonGroup"] button { min-height: 44px; }
[data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid #e7ecf3; padding-bottom: 8px; }
[data-baseweb="tab"] { padding: 10px 14px; border-radius: 12px; font-weight: 600; }
[data-baseweb="tab"][aria-selected="true"] { background: #eaf2ff; color: #216bdd; }
[data-testid="stPlotlyChart"] { border-radius: 20px; overflow: hidden; background: #fff; border: 1px solid #e7ecf3; }
[data-testid="stPlotlyChart"] .js-plotly-plot,
[data-testid="stPlotlyChart"] .main-svg,
[data-testid="stPlotlyChart"] .draglayer rect { touch-action: pan-y !important; }
.btc-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.btc-logo {
    display: grid; place-items: center; width: 42px; height: 42px; border-radius: 15px;
    background: #3182f6; color: #fff; font-size: 27px; font-weight: 800;
}
.btc-brand h1 { font-size: 18px; font-weight: 800; letter-spacing: -.02em; margin: 0; padding: 0; color: #191f28; }
.btc-brand p { color: #66758b; font-size: 12px; margin: 2px 0 0; }
.btc-brand-tag { margin-left: auto; color: #66758b; font-size: 12px; }
.btc-hero {
    padding: 23px 26px; border: 1px solid #e7ecf3; border-radius: 24px; margin-bottom: 14px;
    background: #fff; box-shadow: 0 5px 24px #163b6410; position: relative; overflow: hidden;
}
.btc-hero-top { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.btc-market { font-size: 18px; font-weight: 700; }
.btc-badge { border: 1px solid #e4eaf3; border-radius: 999px; padding: 4px 9px; font-size: 11px; color: #53647b; background: #f8fafc; }
.btc-badge-live { color: #087855; background: #e9f8f0; border-color: #d0efe1; }
.btc-badge-demo { color: #8a5c11; background: #fff5df; border-color: #f1dfb5; }
.btc-price-label { margin-top: 18px; color: #66758b; font-size: 12px; }
.btc-price { font-size: clamp(34px, 5vw, 52px); font-weight: 780; line-height: 1.15; letter-spacing: -.055em; margin-top: 4px; font-variant-numeric: tabular-nums; }
.btc-price small { font-size: 14px; letter-spacing: 0; color: #66758b; font-weight: 500; margin-left: 10px; }
.btc-price-meta { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 12px; color: #66758b; font-size: 12px; }
.btc-up { color: #09845c; } .btc-down { color: #d63851; }
.btc-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0 0 14px; }
.btc-card { padding: 15px 18px; border-radius: 18px; border: 1px solid #e7ecf3; background: #fff; }
.btc-card-label { font-size: 12px; color: #66758b; margin-bottom: 6px; }
.btc-card-value { font-size: 24px; font-weight: 750; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.btc-card-value small { font-size: 12px; color: #66758b; font-weight: 400; letter-spacing: 0; }
.btc-card-hint { font-size: 11px; color: #66758b; margin-top: 4px; }
.btc-meter { height: 4px; background: #e8eff9; border-radius: 10px; margin-top: 12px; overflow: hidden; }
.btc-meter span { height: 100%; display: block; background: #3182f6; }
.btc-indicator-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 10px 0; }
.btc-indicator-card { background: #fff; border: 1px solid #e7ecf3; border-radius: 18px; padding: 18px; min-width: 0; }
.btc-indicator-label { color: #53647b; font-size: 13px; margin-bottom: 9px; }
.btc-indicator-card strong { display: block; font-size: 20px; letter-spacing: -.03em; line-height: 1.4; }
.btc-indicator-value { font-size: 15px; color: #333d4b; font-variant-numeric: tabular-nums; margin-top: 7px; overflow-wrap: anywhere; }
.btc-indicator-card p { color: #53647b; font-size: 13px; line-height: 1.6; margin: 10px 0 0; }
.btc-indicator-up strong { color: #087855; } .btc-indicator-down strong { color: #c02c46; }
.btc-indicator-caution strong { color: #95600b; }
@media (max-width: 760px) {
    .btc-indicator-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
    .btc-indicator-card { padding: 14px 12px; }
    .btc-indicator-card strong { font-size: 17px; }
}
@media (max-width: 350px) { .btc-indicator-grid { grid-template-columns: 1fr; } }
.btc-section-label { font-size: 12px; font-weight: 650; color: #3182f6; margin: 12px 0 5px; }
.btc-horizons { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0; margin-bottom: 16px; background: #fff; border: 1px solid #e7ecf3; border-radius: 18px; overflow: hidden; }
.btc-horizon { padding: 13px 15px; border-right: 1px solid #edf1f6; text-align: center; }
.btc-horizon:last-child { border-right: 0; }
.btc-horizon strong { display: block; font-size: 19px; margin: 4px 0 2px; }
.btc-horizon p { margin: 2px 0; font-size: 11px; color: #66758b; }
.btc-signal { border: 1px solid #d9e8ff; border-radius: 22px; background: #eaf3ff; padding: 20px 24px; margin: 0 0 14px; }
.btc-signal h2 { margin: 6px 0 8px; padding: 0; font-size: clamp(23px, 3vw, 29px); }
.btc-signal p { margin: 0; color: #425c7e; font-size: 14px; line-height: 1.65; }
.btc-signal-label { color: #216bdd; font-size: 11px; font-weight: 750; }
.btc-signal-sell { background: #fff1f3; border-color: #f4dbe1; }
.btc-signal-sell .btc-signal-label { color: #bd3150; }
.btc-ichimoku { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }
.btc-ichimoku article { border: 1px solid #e7ecf3; border-radius: 16px; background: #fff; padding: 15px 17px; }
.btc-ichimoku strong { display: block; font-size: 18px; margin: 5px 0; }
.btc-ichimoku p { color: #66758b; font-size: 12px; margin: 0; }
[data-testid="stTabs"] [role="tablist"] { gap: 6px; padding: 6px; border-radius: 16px; background: #eef2f8; }
[data-testid="stTabs"] [role="tab"] { min-height: 44px; border-radius: 11px; padding: 10px 14px; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] { background: white; color: #216bdd; box-shadow: 0 2px 8px #163b6410; }
[data-testid="stButton"] button, [data-testid="stButtonGroup"] button, [role="tab"] {
    transition: background-color 150ms ease, border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}
[data-testid="stButton"] button:hover { transform: translateY(-1px); box-shadow: 0 3px 10px #163b6415; }
[data-testid="stButton"] button:active { transform: scale(.985); }
button:focus-visible { outline: 3px solid #3182f666; outline-offset: 3px; }
.btc-forecast-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0 18px; }
.btc-forecast-cards article { border-radius: 18px; padding: 18px; border: 1px solid #e7ecf3; background: #fff; }
.btc-forecast-cards article:first-child { background: linear-gradient(135deg, #eaf3ff, #f5f9ff); border-color: #d9e8ff; }
.btc-forecast-cards p { margin: 0 0 8px; color: #66758b; font-size: 12px; }
.btc-forecast-cards strong { display: block; font-size: clamp(19px, 2vw, 26px); letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
.btc-forecast-cards span { display: block; margin-top: 8px; color: #66758b; font-size: 11px; }
.btc-replay-summary { border: 1px solid #f5dfb9; border-radius: 14px; background: #fff9ef; padding: 13px 16px; margin: 0 0 12px; }
.btc-replay-summary strong { display: block; color: #8f570c; font-size: 15px; }
.btc-replay-summary span { display: block; color: #746653; margin-top: 5px; font-size: 12px; }
.btc-match-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0 16px; }
.btc-match-cards article { padding: 14px; border: 1px solid #e7ecf3; border-radius: 16px; background: #fff; }
.btc-match-cards span { color: #66758b; font-size: 11px; display: block; }
.btc-match-cards strong { display: block; font-size: 24px; margin-top: 5px; font-variant-numeric: tabular-nums; }
.btc-match-cards small { color: #66758b; font-size: 11px; font-weight: 400; }
.btc-chart-summary { background: white; border: 1px solid #e7ecf3; border-radius: 18px; padding: 16px 20px; }
.btc-chart-summary span { display: block; color: #66758b; font-size: 12px; }
.btc-chart-summary strong { display: block; font-size: 28px; letter-spacing: -.035em; margin: 5px 0; }
.btc-chart-summary small { font-size: 13px; color: #66758b; }
@media (prefers-reduced-motion: reduce) {
    [data-testid="stButton"] button, [data-testid="stButtonGroup"] button, [role="tab"] { transition: none; }
    [data-testid="stButton"] button:hover, [data-testid="stButton"] button:active { transform: none; }
}
@media (max-width: 760px) {
    .st-key-market_controls [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 8px 12px; }
    .st-key-market_controls [data-testid="stColumn"] { min-width: 0 !important; }
    .st-key-market_controls [data-testid="stColumn"]:nth-child(1) { flex: 3 1 58%; }
    .st-key-market_controls [data-testid="stColumn"]:nth-child(2) { flex: 2 1 34%; }

    .btc-match-cards article { padding: 10px; }
    .btc-match-cards strong { font-size: 20px; }
    .btc-forecast-cards { grid-template-columns: 1fr; gap: 8px; }
    .btc-forecast-cards article { padding: 14px 17px; }
    .btc-forecast-cards strong { font-size: 23px; }
    [data-testid="stTabs"] [role="tab"] { padding: 10px 12px; font-size: 13px; }
    .block-container { padding: 4.1rem 1rem 2rem; }
    .btc-brand-tag { display: none; }
    .btc-hero { padding: 18px 20px; border-radius: 20px; }
    .btc-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
    .btc-card { padding: 12px 14px; }
    .btc-card-value { font-size: 22px; }
    .btc-card-hint { font-size: 11px; }
    .btc-horizon { padding: 10px 2px; }
    .btc-horizon strong { font-size: 17px; }
    .btc-horizon p { font-size: 10px; }
    .btc-horizon .btc-card-label { font-size: 11px; }
    .btc-signal { padding: 16px 18px; }
    .btc-signal p { font-size: 13px; }
    .btc-ichimoku { grid-template-columns: 1fr; gap: 8px; }
    .btc-ichimoku article { padding: 12px 15px; }
    [data-baseweb="tab"] { padding: 10px 12px; font-size: 13px; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
}
</style>
"""

BRAND = """
<div class="btc-brand">
  <div class="btc-logo" aria-hidden="true">₿</div>
  <div><h1>BTC SIGNAL LAB</h1><p>지금의 흐름, 근거까지 쉽게</p></div>
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
 <div class="btc-price">{price:,.2f}<small>{escape(quote)}</small></div>
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
        "매수": "매수 조건이 모였어요",
        "매도": "하락 흐름을 경계할 때예요",
        "관망": "지금은 기다릴 때예요",
    }
    if signal.mode == "눌림목 분할매수":
        headings["매수"] = "조정된 가격에서 나눠 살 조건이에요"
        reason = "가격 할인과 하락 압력 둔화를 확인했어요. 단기 상승 전에도 검토할 수 있어요. 주봉·월봉 방향과 일봉 변동성을 함께 확인한 신호예요."
    elif signal.action == "매수":
        reason = "일봉·주봉·월봉이 상승 방향을 지지해요. 단기 상승 여부와 함께 일봉 변동성과 비용 후 손익비를 확인한 신호예요."
    elif signal.mode == "과열 분할매도":
        headings["매도"] = "과열 구간에서 나눠 팔 때예요"
        reason = "일봉 RSI와 중기 기준 대비 가격 이격이 커요. 현물 보유 중이라면 분할 이익 실현을 검토하는 신호예요."
    elif signal.action == "매도":
        reason = "일봉·주봉의 하락 방향이 일치해요. 현물을 보유 중이라면 보유분 축소를 검토하는 신호예요."
    elif signal.ready_frames < 5:
        reason = f"5개 중 {signal.ready_frames}개 시간대만 준비됐어요. 부족한 데이터를 확인할 때까지 판단을 보류해요."
    elif any("극단적 변동성" in item for item in signal.reasons):
        reason = "가격 변동이 너무 커요. 방향보다 변동 위험을 먼저 확인할 때예요."
    elif signal.position.broken_support:
        reason = "확정 지지 구간이 깨졌어요. 낮은 가격만 보고 진입하기보다 하락이 진정되는지 먼저 확인해요."
    elif any("0.6배" in item for item in signal.reasons):
        reason = "일봉·4시간 거래량이 충분하지 않아요. 신규 매수는 잠시 보류해요."
    elif any("RR 조건이 부족" in item for item in signal.reasons):
        reason = "가격이나 방향은 관심 구간이지만 비용 후 손익비가 부족해요. 일봉 진입 조건을 기다려요."
    elif signal.position.value_score >= 65:
        headings["관망"] = "가격은 관심 구간, 진정은 더 확인해요"
        reason = (
            "중기 기준보다 낮은 가격이에요. 장기 방향과 하락 압력 둔화가 함께 확인될 때 분할매수를 검토해요."
        )
    else:
        supported = (
            signal.frames["1w"].score >= 48
            and signal.frames["1M"].score >= 45
            and signal.position.macro_score >= 50
        )
        reason = (
            "장기 흐름은 버티고 있어요. 가격 매력과 하락 진정 조건이 함께 맞을 때 분할매수를 검토해요."
            if supported
            else "주봉·월봉 방향의 지지가 아직 부족해요. 낮아진 가격만으로 새 매수 신호를 내지 않아요."
        )
    kind = {"매수": "buy", "매도": "sell", "관망": "hold"}[signal.action]
    return f'<section class="btc-signal btc-signal-{kind}" aria-label="종합 신호 근거"><span class="btc-signal-label">{signal.action} · 종합 신호 · {escape(signal.mode)}</span><h2>{headings[signal.action]}</h2><p>{escape(reason)}</p></section>'


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
