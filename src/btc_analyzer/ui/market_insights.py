"""Native sentiment and touch-selectable heatmap; no SDK, chart or iframe."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from btc_analyzer.analysis.hourly_heatmap import WEEKDAYS, hourly_heatmap
from btc_analyzer.data.market_context import UTC
from btc_analyzer.data.sentiment import FEAR_SOURCE, LEVELS, FearGreed
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS
from btc_analyzer.ui.market_context import current_context

CSS = """<style>
.btc-insight-card{background:#fff;border:1px solid #e7ecf3;border-radius:20px;padding:18px;min-width:0;margin:0 0 12px;color:#53647b}
.btc-insight-heading{display:flex;justify-content:space-between;align-items:center;gap:8px}.btc-insight-heading strong{font-size:14px;color:#191f28}.btc-insight-badge{font-size:10px;padding:4px 7px;border-radius:7px;background:#f1f4f9;color:#66758b}
.btc-insight-card p{font-size:12px;line-height:1.6;margin:9px 0;overflow-wrap:anywhere}.btc-insight-card small{font-size:10px;color:#75839a}.btc-insight-card a{color:#3182f6;text-decoration:none}
.btc-fear-number{font-size:44px;font-weight:750;letter-spacing:-1px;color:#191f28;line-height:1.1;margin-top:20px}.btc-fear-number small{font-size:13px;letter-spacing:0;font-weight:400}.btc-fear-state{font-size:18px;font-weight:650;margin-top:5px}.btc-fear-state.fear{color:#c36920}.btc-fear-state.greed{color:#087f5b}.btc-fear-state.neutral{color:#53647b}
.btc-fear-gauge{height:8px;border-radius:8px;position:relative;margin:23px 4px 7px;background:linear-gradient(90deg,#e97d74,#e8b76e,#b9c7db,#70bba4,#179a79)}
.btc-fear-gauge i{position:absolute;top:-4px;width:3px;height:16px;border-radius:3px;background:#233551;left:clamp(0px,var(--score),calc(100% - 3px))}.btc-fear-scale{display:flex;justify-content:space-between;font-size:10px;color:#75839a}
.btc-fear-history{width:100%;height:50px;display:block;margin:10px 0 4px}.btc-insight-card[data-status="stale"] .btc-fear-number,.btc-insight-card[data-status="stale"] .btc-fear-state{color:#8793a4}
.btc-heatmap{position:relative;padding-bottom:58px;touch-action:pan-y}.btc-heatmap-grid{display:grid;grid-template-columns:24px repeat(6,minmax(0,1fr));gap:5px;align-items:center}
.btc-heatmap-hour,.btc-heatmap-day{font-size:10px;color:#75839a;text-align:center}.btc-heatmap-hour{padding:4px 0 6px}.btc-heatmap-day{font-weight:600}
.btc-heatmap-cell input{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}.btc-heatmap-cell label{display:flex;align-items:center;justify-content:center;height:34px;font-size:11px;font-weight:650;border-radius:7px;background:var(--cell-bg);color:var(--cell-fg);cursor:pointer;touch-action:pan-y;user-select:none}
.btc-heatmap-cell input:checked+label,.btc-heatmap-cell input:focus-visible+label{outline:2px solid #3182f6;outline-offset:1px}.btc-heatmap-cell .btc-heatmap-detail{display:none;position:absolute;bottom:0;left:0;right:0;height:48px;border-radius:9px;background:#f5f8fc;padding:7px 10px;box-sizing:border-box;font-size:11px;line-height:1.5;color:#53647b;pointer-events:none;font-weight:400}
.btc-heatmap-cell input:checked+label .btc-heatmap-detail{display:block}.btc-heatmap-prompt{position:absolute;bottom:0;left:0;right:0;height:48px;box-sizing:border-box;padding:8px 10px;font-size:11px;line-height:1.5;color:#75839a;background:#f5f8fc;border-radius:9px;pointer-events:none}.btc-heatmap:has(input:checked) .btc-heatmap-prompt{visibility:hidden}
@media(hover:hover){.btc-heatmap-cell label:hover .btc-heatmap-detail{display:block}.btc-heatmap:has(label:hover) .btc-heatmap-prompt{visibility:hidden}.btc-heatmap:has(label:hover) input:checked+label:not(:hover) .btc-heatmap-detail{display:none}}
.btc-heatmap-legend{display:flex;align-items:center;justify-content:flex-end;gap:6px;font-size:10px;color:#75839a;margin:12px 0 6px}.btc-heatmap-legend i{width:70px;height:6px;border-radius:4px;background:linear-gradient(90deg,#eab8bf,#f3f5f8,#9ad6c3)}
@media(max-width:600px){.btc-insight-card{padding:14px;border-radius:16px}.btc-heatmap-grid{gap:4px;grid-template-columns:21px repeat(6,minmax(0,1fr))}.btc-heatmap-cell label{font-size:10px;height:36px}.btc-fear-number{font-size:38px;margin-top:14px}}
</style>"""


def fear_card(feed, now):
    value = feed.value
    if not isinstance(value, FearGreed):
        status = "조회 지연" if feed.error else "불러오는 중"
        return f'<article class="btc-insight-card btc-fear-card" aria-label="코인 공포탐욕지수" data-status="pending"><div class="btc-insight-heading"><strong>공포·탐욕 지수</strong><span class="btc-insight-badge">일별</span></div><div class="btc-fear-number">—</div><p>{status} · 지수가 도착하면 표시해요.</p><small>출처 <a href="{FEAR_SOURCE}" target="_blank" rel="noopener noreferrer">Alternative.me ↗</a></small></article>'
    point = value.latest
    label, tone = LEVELS[point.classification]
    stale = bool(feed.error) or not timedelta(0) <= now - point.timestamp <= timedelta(hours=48)
    status, badge = ("stale", "마지막 값 · 조회 지연") if stale else ("daily", "일별 갱신")
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
    return (
        f'<article class="btc-insight-card btc-fear-card" aria-label="코인 공포탐욕지수" data-status="{status}" data-score="{point.value}">'
        f'<div class="btc-insight-heading"><strong>공포·탐욕 지수</strong><span class="btc-insight-badge">{badge}</span></div>'
        f'<div class="btc-fear-number">{point.value}<small> / 100</small></div><div class="btc-fear-state {tone}">{escape(label)}</div><p>{change_text}</p>'
        f'<div class="btc-fear-gauge" style="--score:{point.value}%" aria-hidden="true"><i></i></div><div class="btc-fear-scale"><span>0 · 공포</span><span>50 · 중립</span><span>100 · 탐욕</span></div>'
        + graph
        + f'<small>최근 {len(value.history)}개 일별 관측 · {stamp:%m.%d %H:%M} KST 기준<br>출처 <a href="{FEAR_SOURCE}" target="_blank" rel="noopener noreferrer">Alternative.me ↗</a> · 코인 시장 심리</small></article>'
    )


@st.fragment(run_every=10)
def render_sentiment():
    st.markdown(fear_card(current_context().feed("fear"), datetime.now(UTC)), unsafe_allow_html=True)


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def cached_heatmap(frame, cutoff, days):
    return hourly_heatmap(frame, cutoff, days)


def heatmap_card(result):
    cells = ['<span class="btc-heatmap-hour">KST</span>']
    cells.extend(
        f'<span class="btc-heatmap-hour">{hour:02d}–{hour + 4:02d}</span>' for hour in range(0, 24, 4)
    )
    for cell in result.cells:
        if cell.hour == 0:
            cells.append(f'<span class="btc-heatmap-day">{WEEKDAYS[cell.weekday]}</span>')
        move = cell.median_return
        displayed = round(move * 100, 2) / 100 if move is not None else None
        number = f"{displayed:+.2%}" if displayed else "0.00%" if displayed is not None else "—"
        intensity = min(1, abs(move) / 0.01) if move is not None else 0
        bg = (
            f"rgba({'8,168,119' if move is not None and move > 0 else '221,82,111'},{0.08 + intensity * 0.26:.3f})"
            if displayed
            else "#f1f4f8"
        )
        fg = (
            "#087f5b"
            if displayed is not None and displayed > 0
            else "#b44460"
            if displayed is not None and displayed < 0
            else "#75839a"
        )
        identifier = f"btc-heat-{result.days}-{cell.weekday}-{cell.hour}"
        detail = f"{WEEKDAYS[cell.weekday]}요일 {cell.hour:02d}~{cell.hour + 4:02d}시 KST · {cell.samples}개 완결 구간"
        note = (
            f"4시간 등락 중앙값 {move:+.2%}" if move is not None else "2개 이상의 관측이 필요해요 · 자료 부족"
        )
        cells.append(
            f'<div class="btc-heatmap-cell" data-weekday="{cell.weekday}" data-hour="{cell.hour}" style="--cell-bg:{bg};--cell-fg:{fg}"><input type="radio" name="btc-heat-choice" id="{identifier}" aria-label="{escape(detail + " · " + note)}"><label for="{identifier}">{number}<span class="btc-heatmap-detail">{escape(detail)}<br>{escape(note)}</span></label></div>'
        )
    dates = (
        f"{result.start.tz_convert('Asia/Seoul'):%m.%d}~{result.end.tz_convert('Asia/Seoul'):%m.%d} KST"
        if result.start is not None
        else "확정 자료 대기"
    )
    return (
        '<article class="btc-insight-card btc-heatmap-card" aria-label="요일 시간대 등락 히트맵">'
        f'<div class="btc-insight-heading"><strong>언제 강하고 약했을까요?</strong><span class="btc-insight-badge">최근 {result.days}일</span></div>'
        '<p>요일 × 4시간 · 색과 숫자로 보는 비트코인 흐름</p><div class="btc-heatmap"><div class="btc-heatmap-grid">'
        + "".join(cells)
        + '</div><div class="btc-heatmap-prompt">칸을 터치하거나 마우스를 올려 등락률과 관측 수를 확인하세요.</div></div>'
        f'<div class="btc-heatmap-legend"><span>하락</span><i></i><span>상승 · 색 농도 ±1%</span></div><small>{dates} · 완결 4시간 구간 {result.blocks}개<br>빈 칸은 자료 부족 · 과거 관측이며 미래 방향을 뜻하지 않아요.</small></article>'
    )


@st.fragment
def render_heatmap(frame, cutoff):
    days = (
        st.segmented_control(
            "히트맵 기간",
            [30, 14],
            default=30,
            format_func=lambda value: f"최근 {value}일",
            key="market_heatmap_days",
        )
        or 30
    )
    result = cached_heatmap(frame, pd.Timestamp(cutoff).floor("h"), days)
    st.markdown(heatmap_card(result), unsafe_allow_html=True)


def render_market_insights(frame, cutoff):
    st.markdown(CSS + "<strong>시장 심리와 시간대 흐름</strong>", unsafe_allow_html=True)
    sentiment, heatmap = st.columns([1, 2], gap="small")
    with sentiment:
        render_sentiment()
    with heatmap:
        render_heatmap(frame, cutoff)
