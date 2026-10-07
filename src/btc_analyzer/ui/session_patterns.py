"""Compact historical observations, sharing the existing hourly download."""

from html import escape

import pandas as pd
import streamlit as st

from btc_analyzer.analysis.session_patterns import session_patterns
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

CSS = """<style>
.btc-pattern-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;margin:10px 0 16px}
.btc-pattern-card{background:#fff;border:1px solid #e5eaf2;border-radius:18px;padding:16px;min-width:0}
.btc-pattern-card h4{font-size:13px;color:#66758b;margin:0 0 8px}.btc-pattern-card strong{font-size:20px;color:#192434}
.btc-pattern-card p{font-size:13px;color:#66758b;line-height:1.6;margin:7px 0 0;overflow-wrap:anywhere}
.btc-pattern-card .up{color:#087f5b}.btc-pattern-card .down{color:#ce4260}
@media(max-width:450px){.btc-pattern-card{padding:12px}.btc-pattern-card strong{font-size:17px}}
</style>"""


@st.cache_data(show_spinner=False, ttl=3600, max_entries=16, hash_funcs=MARKET_HASH_FUNCS)
def cached_patterns(frame, cutoff):
    return session_patterns(frame, cutoff, include_hours=False)


def pattern_cards(result):
    band = result["range"]
    if band:
        title = "최근 6시간은 횡보 흐름" if band["current_flat"] else "최근 횡보가 잦았던 구간"
        value = f"${band['low']:,.0f} ~ ${band['high']:,.0f}"
        meaning = (
            f"최근 72시간의 수신 {band['observed']}시간 중 {band['hours']}시간. 횡보 종가의 중간 80%예요."
        )
        if not band["current_flat"]:
            meaning += " 최근 6시간은 횡보 조건을 벗어났어요."
    else:
        title, value = "최근 횡보 구간", "뚜렷한 반복 없음"
        meaning = "최근 72시간에서 현재 가격 근처의 좁은 구간을 12시간 이상 확인하면 표시해요."
    cards = [(title, value, meaning, "")]
    return (
        '<div class="btc-pattern-grid">'
        + "".join(
            f'<article class="btc-pattern-card"><h4>{escape(title)}</h4><strong class="{tone}">{escape(value)}</strong><p>{escape(meaning)}</p></article>'
            for title, value, meaning, tone in cards
        )
        + "</div>"
    )


def render_session_patterns(frame, cutoff):
    result = cached_patterns(frame, pd.Timestamp(cutoff).floor("h"))
    st.markdown("**최근 횡보 흐름**")
    st.markdown(CSS + pattern_cards(result), unsafe_allow_html=True)
    if result["start"] is not None:
        start, end = (result[key].tz_convert("Asia/Seoul") for key in ("start", "end"))
        st.caption(
            f"관측 {start:%m.%d %H:%M} ~ {end:%m.%d %H:%M} KST · 확정 1시간봉 {result['bars']}개. 최근 횡보 종가의 관측 요약이에요."
        )
