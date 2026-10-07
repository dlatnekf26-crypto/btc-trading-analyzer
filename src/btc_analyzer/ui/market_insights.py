"""Native sentiment and touch-selectable heatmap; no SDK, chart or iframe."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from btc_analyzer.analysis.monthly_heatmap import monthly_heatmap
from btc_analyzer.data.market_context import UTC
from btc_analyzer.data.sentiment import FEAR_SOURCE, LEVELS, FearGreed
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS
from btc_analyzer.ui.market_context import current_context
from btc_analyzer.ui.economic_releases import render_economic_releases

CSS = """<style>
.btc-insight-card{background:#fff;border:1px solid #e7ecf3;border-radius:20px;padding:18px;min-width:0;margin:0 0 12px;color:#53647b}
.btc-insight-heading{display:flex;justify-content:space-between;align-items:center;gap:8px}.btc-insight-heading strong{font-size:14px;color:#191f28}.btc-insight-badge{font-size:10px;padding:4px 7px;border-radius:7px;background:#f1f4f9;color:#66758b}
.btc-insight-card p{font-size:12px;line-height:1.6;margin:9px 0;overflow-wrap:anywhere}.btc-insight-card small{font-size:10px;color:#75839a}.btc-insight-card a{color:#3182f6;text-decoration:none}
.btc-fear-number{font-size:44px;font-weight:750;letter-spacing:-1px;color:#191f28;line-height:1.1;margin-top:20px}.btc-fear-number small{font-size:13px;letter-spacing:0;font-weight:400}.btc-fear-state{font-size:18px;font-weight:650;margin-top:5px}.btc-fear-state.fear{color:#c36920}.btc-fear-state.greed{color:#087f5b}.btc-fear-state.neutral{color:#53647b}
.btc-fear-gauge{height:8px;border-radius:8px;position:relative;margin:23px 4px 7px;background:linear-gradient(90deg,#e97d74,#e8b76e,#b9c7db,#70bba4,#179a79)}
.btc-fear-gauge i{position:absolute;top:-4px;width:3px;height:16px;border-radius:3px;background:#233551;left:clamp(0px,var(--score),calc(100% - 3px))}.btc-fear-scale{display:flex;justify-content:space-between;font-size:10px;color:#75839a}
.btc-fear-history{width:100%;height:50px;display:block;margin:10px 0 4px}.btc-insight-card[data-status="stale"] .btc-fear-number,.btc-insight-card[data-status="stale"] .btc-fear-state{color:#8793a4}
.btc-heatmap{position:relative;padding-bottom:58px;touch-action:pan-y}.btc-heatmap-grid{display:grid;grid-template-columns:42px repeat(12,minmax(0,1fr));gap:5px;align-items:center}
.btc-heatmap-half{display:none}.btc-heatmap-card{container-type:inline-size}.btc-heatmap-grid+.btc-heatmap-grid{margin-top:5px}.btc-heatmap-hour,.btc-heatmap-day{font-size:10px;color:#75839a;text-align:center}.btc-heatmap-hour{padding:4px 0 6px}.btc-heatmap-day{font-weight:600}.btc-heatmap-day small{font-size:8px;font-weight:400;margin-top:2px}
.btc-heatmap-cell input{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}.btc-heatmap-cell label{display:flex;align-items:center;justify-content:center;height:34px;font-size:11px;font-weight:650;border-radius:7px;background:var(--cell-bg);color:var(--cell-fg);cursor:pointer;touch-action:pan-y;user-select:none}
.btc-heatmap-cell input:checked+label,.btc-heatmap-cell input:focus-visible+label{outline:2px solid #3182f6;outline-offset:1px}.btc-heatmap-cell .btc-heatmap-detail{display:none;position:absolute;bottom:0;left:0;right:0;height:48px;border-radius:9px;background:#f5f8fc;padding:7px 10px;box-sizing:border-box;font-size:11px;line-height:1.5;color:#53647b;pointer-events:none;font-weight:400}
.btc-heatmap-cell input:checked+label .btc-heatmap-detail{display:block}.btc-heatmap-prompt{position:absolute;bottom:0;left:0;right:0;height:48px;box-sizing:border-box;padding:8px 10px;font-size:11px;line-height:1.5;color:#75839a;background:#f5f8fc;border-radius:9px;pointer-events:none}.btc-heatmap:has(input:checked) .btc-heatmap-prompt{visibility:hidden}
@media(hover:hover){.btc-heatmap-cell label:hover .btc-heatmap-detail{display:block}.btc-heatmap:has(label:hover) .btc-heatmap-prompt{visibility:hidden}.btc-heatmap:has(label:hover) input:checked+label:not(:hover) .btc-heatmap-detail{display:none}}
.btc-heatmap-legend{display:flex;align-items:center;justify-content:flex-end;gap:6px;font-size:10px;color:#75839a;margin:12px 0 6px}.btc-heatmap-legend i{width:70px;height:6px;border-radius:4px;background:linear-gradient(90deg,#eab8bf,#f3f5f8,#9ad6c3)}
@media(max-width:600px){.btc-insight-card{padding:14px;border-radius:16px}.btc-heatmap-grid{gap:4px;grid-template-columns:38px repeat(6,minmax(0,1fr))}.btc-heatmap-cell label{font-size:10px;height:36px}.btc-fear-number{font-size:38px;margin-top:14px}}
@container(max-width:700px){.btc-heatmap-grid{grid-template-columns:38px repeat(6,minmax(0,1fr))}.btc-heatmap-half{display:block}.btc-heatmap-cell label{font-size:10px}}
</style>"""


def fear_card(feed, now):
    value = feed.value
    if not isinstance(value, FearGreed):
        status = "조회 지연" if feed.error else "불러오는 중"
        return f'<article class="btc-insight-card btc-fear-card" aria-label="코인 공포탐욕지수" data-status="pending"><div class="btc-insight-heading"><strong>공포·탐욕 지수</strong><span class="btc-insight-badge">자동 확인</span></div><div class="btc-fear-number">—</div><p>{status} · 지수가 도착하면 표시해요.</p><small>출처 <a href="{FEAR_SOURCE}" target="_blank" rel="noopener noreferrer">Alternative.me ↗</a></small></article>'
    point = value.latest
    label, tone = LEVELS[point.classification]
    stale = bool(feed.error) or not timedelta(0) <= now - point.timestamp <= timedelta(hours=48)
    status, badge = ("stale", "마지막 값 · 조회 지연") if stale else ("daily", "자동 확인 · 일별 지수")
    change = value.daily_change
    change_text = f"전일보다 {change:+d}점" if change is not None else "전일 비교 자료 없음"
    start, end = value.history[0].timestamp, point.timestamp
    span = max(1, (end - start).total_seconds())
    path, previous = [], None
    for item in value.history:
        x, y = (item.timestamp - start).total_seconds() / span * 280, 44 - item.value * 0.4
        command = (
            "M" if previous is None or item.timestamp.date() - previous.date() != timedelta(days=1) else "L"
        )
        path.append(f"{command}{x:.1f},{y:.1f}")
        previous = item.timestamp
    graph = f'<svg class="btc-fear-history" viewBox="0 0 280 50" preserveAspectRatio="none" role="img" aria-label="최근 일별 공포탐욕지수"><path d="{" ".join(path)}" fill="none" stroke="#819bbd" stroke-width="2"/></svg>'
    if len(value.history) == 1:
        graph = graph.replace(
            "</svg>", f'<circle cx="0" cy="{44 - point.value * 0.4:.1f}" r="2" fill="#819bbd"/></svg>'
        )
    stamp = point.timestamp.astimezone(ZoneInfo("Asia/Seoul"))
    checked = feed.updated_at.astimezone(ZoneInfo("Asia/Seoul")) if feed.updated_at else None
    check_text = f"마지막 확인 {checked:%m.%d %H:%M} KST" if checked else "확인 시각 대기"
    return (
        f'<article class="btc-insight-card btc-fear-card" aria-label="코인 공포탐욕지수" data-status="{status}" data-score="{point.value}">'
        f'<div class="btc-insight-heading"><strong>공포·탐욕 지수</strong><span class="btc-insight-badge">{badge}</span></div>'
        f'<div class="btc-fear-number">{point.value}<small> / 100</small></div><div class="btc-fear-state {tone}">{escape(label)}</div><p>{change_text}</p>'
        f'<div class="btc-fear-gauge" style="--score:{point.value}%" aria-hidden="true"><i></i></div><div class="btc-fear-scale"><span>0 · 공포</span><span>50 · 중립</span><span>100 · 탐욕</span></div>'
        + graph
        + f'<small>최근 {len(value.history)}개 일별 관측 · {stamp:%m.%d %H:%M} KST 기준<br>출처 <a href="{FEAR_SOURCE}" target="_blank" rel="noopener noreferrer">Alternative.me ↗</a> · 코인 시장 심리<br>1분마다 최신 값 확인 · 원자료는 일별 발표<br>{check_text}</small></article>'
    )


@st.fragment(run_every=10)
def render_sentiment():
    st.markdown(fear_card(current_context().feed("fear"), datetime.now(UTC)), unsafe_allow_html=True)


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def cached_heatmap(frame, cutoff, years):
    return monthly_heatmap(frame, cutoff, years)


def heatmap_cell(cell):
    value = cell.change
    shown = round(value * 100, 2) / 100 if value is not None else None
    number = (
        f"{shown:+.2%}"
        if shown
        else "0.00%"
        if shown is not None
        else "진행"
        if cell.status == "open"
        else "—"
    )
    if cell.status == "partial":
        number += "*"
    intensity = min(1, abs(value) / 0.3) if value is not None else 0
    bg = (
        f"rgba({'8,168,119' if shown > 0 else '221,82,111'},{0.08 + intensity * 0.26:.3f})"
        if shown
        else "#f1f4f8"
    )
    fg = "#087f5b" if shown and shown > 0 else "#b44460" if shown and shown < 0 else "#75839a"
    identifier = f"btc-month-{cell.year or 'mean'}-{cell.month}"
    title = (
        f"{cell.year}년 {cell.month:02d}월"
        if cell.year
        else f"{cell.month}월 역사적 평균 · {cell.samples}개 연도"
    )
    note = (
        f"월 시가→종가 {value:+.2%}"
        if cell.year and value is not None
        else f"관측 월 등락률 평균 {value:+.2%}"
        if value is not None
        else "아직 마감하지 않은 월 · 평균에서 제외"
        if cell.status == "open"
        else "자료 없음 또는 미마감 · 평균에서 제외"
    )
    if cell.status == "partial":
        note += " · 거래 시작 부분월 · 평균 제외"
    return f'<div class="btc-heatmap-cell" data-year="{cell.year or "mean"}" data-month="{cell.month}" data-status="{cell.status}" style="--cell-bg:{bg};--cell-fg:{fg}"><input type="radio" name="btc-heat-choice" id="{identifier}" aria-label="{escape(title + " · " + note)}"><label for="{identifier}">{number}<span class="btc-heatmap-detail">{escape(title)}<br>{escape(note)}</span></label></div>'


def heatmap_card(result):
    header = ['<span class="btc-heatmap-hour">연도</span>']
    for month in range(1, 13):
        if month == 7:
            header.append('<span class="btc-heatmap-hour btc-heatmap-half">연도</span>')
        header.append(f'<span class="btc-heatmap-hour">{month}월</span>')
    rows = ['<div class="btc-heatmap-grid">' + "".join(header) + "</div>"]
    for year, values in [
        (None, result.averages),
        *((year, tuple(cell for cell in result.cells if cell.year == year)) for year in result.years),
    ]:
        label = str(year) if year else "평균"
        row = [f'<span class="btc-heatmap-day">{label}<small class="btc-heatmap-half">1–6월</small></span>']
        for cell in values:
            if cell.month == 7:
                row.append(
                    f'<span class="btc-heatmap-day btc-heatmap-half">{label}<small>7–12월</small></span>'
                )
            row.append(heatmap_cell(cell))
        rows.append('<div class="btc-heatmap-grid">' + "".join(row) + "</div>")
    period = f"{result.years[-1]}–{result.years[0]}" if result.years else "자료 대기"
    return (
        '<article class="btc-insight-card btc-heatmap-card" aria-label="연도별 월간 등락 히트맵">'
        f'<div class="btc-insight-heading"><strong>비트코인 월별 등락</strong><span class="btc-insight-badge">{period}</span></div>'
        '<p>여러 해의 1~12월 · 초록 상승 / 빨강 하락</p><div class="btc-heatmap">'
        + "".join(rows)
        + '<div class="btc-heatmap-prompt">칸을 터치하거나 마우스를 올려 해당 월의 등락률을 확인하세요.</div></div>'
        f'<div class="btc-heatmap-legend"><span>하락</span><i></i><span>상승 · 색 농도 ±30%</span></div><small>Binance UTC 월봉 · 마감 {result.bars}개월 · 선택 이력의 월별 평균<br>진행 중/빈 칸은 평균 제외 · * 거래 시작 부분월도 평균에서 제외해요.</small></article>'
    )


@st.fragment
def render_heatmap(frame, cutoff):
    years = (
        st.segmented_control(
            "히트맵 이력",
            [0, 5],
            default=0,
            format_func=lambda value: "전체 이력" if value == 0 else "최근 5년",
            key="market_heatmap_years",
        )
        or 0
    )
    result = cached_heatmap(frame, pd.Timestamp(cutoff).floor("h"), years)
    st.markdown(heatmap_card(result), unsafe_allow_html=True)


def render_market_insights(frame, cutoff):
    st.markdown(CSS + "<strong>시장 심리와 월별 흐름</strong>", unsafe_allow_html=True)
    sentiment, heatmap = st.columns([1, 2], gap="small")
    with sentiment:
        render_sentiment()
    with heatmap:
        render_heatmap(frame, cutoff)
    render_economic_releases()
