"""Shared source-version-safe calendar, visible without opening a forecast."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from btc_analyzer import __checkout_signature__
from btc_analyzer.data.economic_calendar import CALENDAR_REFRESH, fetch_calendar, upcoming_events
from btc_analyzer.data.market_context import MarketContextService, UTC

ZONE = ZoneInfo("Asia/Seoul")
CSS = """<style>
.btc-calendar-card{border:1px solid #e7ecf3;border-radius:18px;background:#fff;padding:16px;margin:10px 0;color:#53647b;font-size:12px;touch-action:pan-y}
.btc-calendar-event{display:grid;grid-template-columns:110px minmax(0,1fr) 80px 80px;gap:8px;align-items:center;border-bottom:1px solid #edf1f6;padding:13px 0}.btc-calendar-event:last-of-type{border:0}.btc-calendar-event strong{display:block;font-size:14px;color:#191f28}.btc-calendar-event small{display:block;font-size:10px;color:#75839a;margin:3px 0}.btc-calendar-event time{font-size:12px;font-weight:600;color:#53647b}.btc-calendar-event b{font-size:15px;color:#191f28}.btc-calendar-card a{color:#3182f6;text-decoration:none}.btc-calendar-card p{font-size:12px;line-height:1.6;margin:8px 0}.btc-calendar-next{font-size:10px;display:block;color:#3182f6;margin-bottom:4px}.btc-calendar-card footer{font-size:10px;color:#75839a;line-height:1.7;margin-top:10px}
@media(max-width:650px){.btc-calendar-event{grid-template-columns:90px minmax(0,1fr)}.btc-calendar-value{padding-left:0}.btc-calendar-event strong{font-size:13px}.btc-calendar-card{padding:13px}}
</style>"""


@st.cache_resource(show_spinner=False, max_entries=1, on_release=lambda service: service.close())
def calendar_service(source_version):
    return MarketContextService(
        fetcher=fetch_calendar,
        keys=("calendar",),
        refresh_intervals={"calendar": CALENDAR_REFRESH},
        workers=1,
    )


def releases_card(feed, now):
    events = upcoming_events(feed, now)
    if not events:
        old = feed.updated_at is not None and not timedelta(0) <= now - feed.updated_at <= timedelta(hours=2)
        text = (
            "발표 일정·예상치 조회 지연 · 확인된 자료가 도착하면 표시해요."
            if feed.error or old
            else "주요 발표와 시장 예상치를 확인하고 있어요."
            if feed.loading or feed.updated_at is None
            else "이번 주 공개 자료에 확인 가능한 예정 주요 발표가 없어요."
        )
        return f'<article class="btc-calendar-card" aria-label="주요 지표 발표와 예상치" data-status="pending"><p>{text}</p><a href="https://www.forexfactory.com/calendar" target="_blank" rel="noopener noreferrer">경제 캘린더 출처 보기 ↗</a></article>'
    rows = []
    for event in events[:6]:
        stamp = event.at.astimezone(ZONE)
        date = "오늘" if stamp.date() == now.astimezone(ZONE).date() else f"{stamp:%m.%d}"
        remaining = event.at - now
        timing = (
            f"{int(remaining.total_seconds() // 60)}분 후" if remaining < timedelta(hours=1) else "발표 예정"
        )
        rows.append(
            f'<div class="btc-calendar-event"><time datetime="{event.at.isoformat()}"><span class="btc-calendar-next">{timing}</span>{date} {stamp:%H:%M}<small>KST · 미국</small></time>'
            f"<div><strong>{escape(event.label)}</strong><small>{escape(event.title)}</small></div>"
            f'<div class="btc-calendar-value"><small>시장 예상</small><b>{escape(event.forecast or "미제공")}</b></div>'
            f'<div class="btc-calendar-value"><small>이전 발표</small><b>{escape(event.previous or "미제공")}</b></div></div>'
        )
    checked = feed.updated_at.astimezone(ZONE)
    return (
        '<article class="btc-calendar-card" aria-label="주요 지표 발표와 예상치" data-status="ready">'
        + "".join(rows)
        + f'<footer>이번 주 공개 일정 · 가까운 주요 발표 최대 6건 · 확인 {checked:%m.%d %H:%M} KST<br>예상치는 시장 컨센서스 · 실제 발표값과 달라요. 미제공 값은 채우지 않아요.<br><a href="https://www.forexfactory.com/calendar" target="_blank" rel="noopener noreferrer">Forex Factory / Fair Economy · 출처 보기 ↗</a></footer></article>'
    )


@st.fragment(run_every=5)
def render_economic_releases():
    st.markdown("**주요 지표 발표와 예상치**")
    feed = calendar_service(__checkout_signature__).snapshot().feed("calendar")
    st.markdown(CSS + releases_card(feed, datetime.now(UTC)), unsafe_allow_html=True)
