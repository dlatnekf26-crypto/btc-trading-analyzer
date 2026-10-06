"""Compact historical observations, sharing the existing hourly download."""

from html import escape

import pandas as pd
import streamlit as st

from btc_analyzer.analysis.session_patterns import session_patterns
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

CSS = """<style>
.btc-pattern-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:10px 0 16px}
.btc-pattern-card{background:#fff;border:1px solid #e5eaf2;border-radius:18px;padding:16px;min-width:0}
.btc-pattern-card h4{font-size:13px;color:#66758b;margin:0 0 8px}.btc-pattern-card strong{font-size:20px;color:#192434}
.btc-pattern-card p{font-size:13px;color:#66758b;line-height:1.6;margin:7px 0 0;overflow-wrap:anywhere}
.btc-pattern-card .up{color:#087f5b}.btc-pattern-card .down{color:#ce4260}
@media(max-width:450px){.btc-pattern-card{padding:12px}.btc-pattern-card strong{font-size:17px}}
</style>"""


@st.cache_data(show_spinner=False, ttl=3600, max_entries=16, hash_funcs=MARKET_HASH_FUNCS)
def cached_patterns(frame, cutoff):
    return session_patterns(frame, cutoff)


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
    hours = result["hours"]
    for direction, label, tone in (
        ("up", "상승 빈도가 가장 높았던 시간", "up"),
        ("down", "하락 빈도가 가장 높았던 시간", "down"),
    ):
        if not hours:
            cards.append((label, "표본을 모으는 중", "시간별 20개 이상의 확정 봉이 필요해요.", ""))
            continue
        best = max(hours, key=lambda row: (row[direction] / row["samples"], row["samples"], -row["hour"]))
        hour = best["hour"]
        count, total = best[direction], best["samples"]
        meaning = f"{total}일 중 {count}회 · {count / total:.0%}. ±0.15% 이내는 보합으로 제외해요."
        if count / total <= 0.5:
            meaning += " 절반 이하라 방향성이 약해요."
        cards.append((label, f"{hour:02d}~{(hour + 1) % 24:02d}시 KST", meaning, tone))
    if hours:
        best = max(hours, key=lambda row: row["median_move"])
        hour = best["hour"]
        cards.append(
            (
                "움직임이 가장 컸던 시간",
                f"{hour:02d}~{(hour + 1) % 24:02d}시 KST",
                f"시간당 등락 크기 중앙값 {best['median_move']:.2%} · {best['samples']}일 관측.",
                "",
            )
        )
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
    st.markdown("**요즘 흐름과 자주 움직인 시간**")
    st.markdown(CSS + pattern_cards(result), unsafe_allow_html=True)
    if result["start"] is not None:
        start, end = (result[key].tz_convert("Asia/Seoul") for key in ("start", "end"))
        st.caption(
            f"관측 {start:%m.%d %H:%M} ~ {end:%m.%d %H:%M} KST · 확정 1시간봉 {result['bars']}개. 시간대 통계는 과거 빈도이며 미래 확률이나 매매 시각 추천은 아니에요."
        )
