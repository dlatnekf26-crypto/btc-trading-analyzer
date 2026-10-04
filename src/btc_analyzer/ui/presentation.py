"""Responsive dashboard presentation. Escape market text before rendering HTML."""

from html import escape

from btc_analyzer.strategy.signal_engine import Analysis
from btc_analyzer.strategy.composite import CompositeSignal, FRAME_LABELS, FRAME_WEIGHTS


CSS = """
<style>
:root { --btc-muted: #a0aec4; --btc-line: #233047; --btc-mint: #4adeb8; }
.stApp { background: radial-gradient(ellipse at 78% 0%, #142438 0%, transparent 42%), #080c14; }
html, body, [class*="css"], .stApp {
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Pretendard', 'Segoe UI', sans-serif;
}
[data-testid="stHeader"] { background: rgba(8, 12, 20, .86); }
.block-container { max-width: 1480px; padding: 4.5rem 2.2rem 3rem; }
[data-testid="stSidebar"] { background: #0d1421; border-right: 1px solid #233047; }
[data-testid="stSidebar"] .block-container { padding: 1rem; }
h1, h2, h3 { letter-spacing: -.04em; }
p, li { line-height: 1.7; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #a0aec4; }
[data-testid="stMetric"] {
    background: #101a2b; padding: 16px; border: 1px solid #233047; border-radius: 16px;
}
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; font-size: 1.8rem; }
[data-testid="stMetricLabel"] { color: #a0aec4; }
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
    border-radius: 12px; min-height: 44px; font-weight: 600;
}
[data-baseweb="tab-list"] { gap: 5px; border-bottom: 1px solid #233047; padding-bottom: 8px; }
[data-baseweb="tab"] { padding: 12px 16px; border-radius: 10px; font-weight: 600; }
[data-baseweb="tab"][aria-selected="true"] { background: #12312e; color: #80f0d5; }
.btc-brand { display: flex; align-items: center; gap: 13px; margin-bottom: 22px; }
.btc-logo {
    display: grid; place-items: center; width: 44px; height: 44px; border-radius: 14px;
    background: #f4b841; color: #101725; font-size: 29px; font-weight: 800;
}
.btc-brand h1 { font-size: 19px; font-weight: 800; letter-spacing: .035em; margin: 0; padding: 0; color: #eff5fb; }
.btc-brand p { color: #a0aec4; font-size: 12px; margin: 2px 0 0; }
.btc-brand-tag { margin-left: auto; color: #a0aec4; font-size: 11px; letter-spacing: .12em; }
.btc-hero {
    padding: 28px 30px; border: 1px solid #29415b; border-radius: 24px; margin-bottom: 16px;
    background: linear-gradient(120deg, #15253a, #0e1827 65%); position: relative; overflow: hidden;
}
.btc-hero-top { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.btc-market { font-size: 18px; font-weight: 700; }
.btc-badge { border: 1px solid #385267; border-radius: 999px; padding: 4px 10px; font-size: 12px; color: #c3d0e2; }
.btc-badge-live { color: #8bf1d7; background: #15332f; border-color: #285b4f; }
.btc-badge-demo { color: #ffd98b; background: #382b15; border-color: #6c542a; }
.btc-price-label { margin-top: 24px; color: #a0aec4; font-size: 12px; }
.btc-price { font-size: clamp(34px, 5vw, 57px); font-weight: 750; line-height: 1.15; letter-spacing: -.05em; margin-top: 4px; font-variant-numeric: tabular-nums; }
.btc-price small { font-size: 16px; letter-spacing: 0; color: #a0aec4; font-weight: 500; margin-left: 10px; }
.btc-price-meta { display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 14px; color: #a0aec4; font-size: 13px; }
.btc-up { color: #76e6c5; } .btc-down { color: #ff98ac; }
.btc-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 22px; }
.btc-card { padding: 19px 20px; border-radius: 18px; border: 1px solid #233047; background: #101827; }
.btc-card-label { font-size: 12px; color: #a0aec4; margin-bottom: 10px; }
.btc-card-value { font-size: 26px; font-weight: 700; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.btc-card-value small { font-size: 13px; color: #a0aec4; font-weight: 400; letter-spacing: 0; }
.btc-card-hint { font-size: 13px; color: #b7c5d8; margin-top: 5px; }
.btc-meter { height: 4px; background: #24334b; border-radius: 10px; margin-top: 16px; overflow: hidden; }
.btc-meter span { height: 100%; display: block; background: linear-gradient(90deg, #3baab2, #6eebc9); }
.btc-section-label { font-size: 11px; color: #83bdb6; letter-spacing: .16em; margin: 14px 0 4px; }
.btc-horizons { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 22px; }
.btc-horizon { background: #101827; border: 1px solid #233047; border-radius: 16px; padding: 15px; }
.btc-horizon strong { display: block; font-size: 22px; margin: 6px 0; }
.btc-horizon p { margin: 3px 0; font-size: 12px; color: #a0aec4; }
.btc-signal { border: 1px solid #355265; border-radius: 20px; background: #112333; padding: 20px 24px; margin: 16px 0; }
.btc-signal h2 { margin: 0 0 8px; padding: 0; font-size: 27px; }
.btc-signal p { margin: 0; color: #c3d0e2; }
@media (max-width: 760px) {
    .block-container { padding: 4.1rem 1rem 2rem; }
    .btc-brand-tag { display: none; }
    .btc-hero { padding: 22px 20px; border-radius: 20px; }
    .btc-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
    .btc-card { padding: 15px; }
    .btc-card-value { font-size: 22px; }
    .btc-horizons { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .btc-horizon:last-child { grid-column: 1 / -1; }
    .btc-signal { padding: 18px; }
    [data-baseweb="tab"] { padding: 10px 12px; font-size: 13px; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
}
</style>
"""

BRAND = """
<div class="btc-brand">
  <div class="btc-logo" aria-hidden="true">₿</div>
  <div><h1>BTC SIGNAL LAB</h1><p>가격부터 근거까지, 한눈에 보는 비트코인 분석</p></div>
  <span class="btc-brand-tag">SPOT MARKET / RESEARCH</span>
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
    color = "btc-up" if signal.action == "매수" else "btc-down" if signal.action == "매도" else ""
    explanation = {
        "매수": "방향과 진입 조건 충족 · 1시간봉 진입 영역 확인",
        "매도": "현물 보유분 축소 검토 · 신규 숏 진입 신호 아님",
        "관망": "방향·거래량·데이터·진입 조건이 갖춰질 때까지 관찰",
    }[signal.action]
    cards = [
        ("5개 시간대 종합 판단", f'<span class="{color}">{signal.action}</span>', explanation),
        ("종합 상승 우위", f"{signal.score.overall:.1f}<small> / 100</small>", korean(signal.score.label)),
        ("방향 일치", f"{signal.agreement}<small> / 5개 시간대</small>", "60 이상 상승 · 40 이하 하락"),
        (
            "지표 데이터 충족",
            f"{signal.quality:.0f}<small> %</small>",
            f"핵심 지표 준비 {signal.ready_frames}/5 · 성공 확률 아님",
        ),
    ]
    html = '<section class="btc-summary" aria-label="분석 요약">'
    for label, value, hint in cards:
        html += f'<div class="btc-card"><div class="btc-card-label">{escape(label)}</div><div class="btc-card-value">{value}</div><div class="btc-card-hint">{escape(hint)}</div></div>'
    html += '</section><section class="btc-horizons" aria-label="다섯 시간대 방향">'
    for tf, frame in signal.frames.items():
        label = "상승 우위" if frame.score >= 60 else "하락 우위" if frame.score <= 40 else "중립"
        color = "btc-up" if frame.score >= 60 else "btc-down" if frame.score <= 40 else ""
        value = f"{frame.score:.1f}" if frame.ready else "대기"
        status = (
            "핵심 지표 대기"
            if not frame.ready
            else "일부 장기 지표 부족"
            if frame.missing
            else "지표 준비 완료"
        )
        html += f'<div class="btc-horizon"><span class="btc-card-label">{FRAME_LABELS[tf]}</span><strong class="{color}">{value}</strong><p>{label if frame.ready else "미반영"} · 비중 {FRAME_WEIGHTS[tf]:.0%}</p><p>{status}</p></div>'
    return html + "</section>"
