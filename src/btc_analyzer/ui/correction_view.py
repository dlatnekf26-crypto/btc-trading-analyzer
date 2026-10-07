"""Compact correction outlook and source-linked release what-if controls."""

from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from btc_analyzer import __checkout_signature__
from btc_analyzer.analysis.correction import correction_outlook, project_event, technical_evidence
from btc_analyzer.candles import candle_boundary
from btc_analyzer.data.economic_calendar import (
    upcoming_events,
    release_condition,
)
from btc_analyzer.indicators.core import indicators
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS
from btc_analyzer.ui.economic_releases import calendar_service


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def correction_context(frame, timeframe, origin, match_ends):
    closed = frame.loc[frame.index < candle_boundary(origin, timeframe)]
    if closed.empty:
        return {}, ()
    features = indicators(closed, timeframe=timeframe)
    keys = ["rsi", "macd_hist", "close", "ema_20"]
    latest = features.iloc[-1][keys].to_dict()
    past = []
    for end in match_ends:
        # Match.end is the opening timestamp of the final matched candle.
        # Its close is known before any of the subsequent outcome candles.
        prior = features.loc[features.index <= end]
        past.append(prior.iloc[-1][keys].to_dict() if not prior.empty else {})
    return latest, tuple(past)


def outlook_html(outlook, timezone, quote):
    if outlook.share is None:
        state, frequency = "조정 판단 대기", outlook.reason
    else:
        state = (
            "조정에 주의할 구간"
            if outlook.share >= 0.6
            else "엇갈리는 과거 흐름"
            if outlook.share >= 0.3
            else "조정 근거가 약해요"
        )
        frequency = f"{outlook.cases}개 중 {outlook.hits}개 하락 · 유사도 가중 비중 {outlook.share:.0%}"
    if outlook.window_start is not None:
        start, end = outlook.window_start.tz_convert(timezone), outlook.window_end.tz_convert(timezone)
        timing = f"{start:%m.%d} ~ {end:%m.%d}"
        price = f"{outlook.low:,.0f} ~ {outlook.high:,.0f}"
        timing_note = "하락 사례의 첫 도달 시점 중간 50% · KST"
        price_note = f"{quote} · 하락 사례의 기간 내 저점 중간 50%"
    else:
        timing, price = "시점 추정 보류", "가격 구간 대기"
        timing_note, price_note = "하락 사례가 2개 이상 필요해요", "적은 사례로 가격대를 만들지 않아요"
    cards = [
        ("과거 흐름으로 본 조정", state, frequency),
        ("이쯤을 주의해서 봐요", timing, timing_note),
        ("조정 사례의 기간 내 저점 범위", price, price_note),
    ]
    return (
        '<div class="btc-correction-cards" aria-label="조정 시나리오">'
        + "".join(
            f"<article><p>{escape(label)}</p><strong>{escape(value)}</strong><span>{escape(note)}</span></article>"
            for label, value, note in cards
        )
        + "</div>"
    )


def render_correction(result, context_values, past_values, news, base, now, timezone, quote):
    st.subheader("조정은 언제 주의할까요?")
    threshold = (
        st.segmented_control(
            "조정 기준 · 분석 종가 대비",
            [0.03, 0.05, 0.10],
            default=0.05,
            format_func=lambda value: f"−{value:.0%}",
            key="correction_threshold",
        )
        or 0.05
    )
    outlook = correction_outlook(result, threshold)
    st.markdown(outlook_html(outlook, timezone, quote), unsafe_allow_html=True)
    st.caption(
        f"조정 기준 {outlook.trigger_price:,.2f} {quote} 이하의 봉 종가 · 고점 대비 낙폭과는 달라요. 과거 경로를 현재 변동성에 맞춰 0.5~2배 환산했어요. 과거 비중은 미래 확률이 아니며, 시점·가격은 조정이 발생한다는 조건의 추정이에요."
    )
    evidence = technical_evidence(context_values)
    if evidence.reasons:
        st.write("**현재 지표** · " + " / ".join(evidence.reasons))
        known = [technical_evidence(values) for values in past_values if values]
        comparable = [item for item in known if len(item.reasons) == len(evidence.reasons) == 3]
        if comparable:
            same = sum(
                (item.pressure > 0) == (evidence.pressure > 0)
                and (item.pressure < 0) == (evidence.pressure < 0)
                for item in comparable
            )
            st.caption(
                f"과거 지표도 비교했어요 · {len(comparable)}개 중 {same}개에서 RSI·MACD·EMA20의 부담/완화 방향이 지금과 같아요. 지표 합산은 설명용이며 유사 사례 비중을 다시 보정하지 않아요."
            )
    else:
        st.caption("현재 지표 이력이 부족해 기술 근거를 추가하지 않았어요.")
    if news is not None and news.effects:
        adverse = [effect.topic for effect in news.effects if effect.direction < 0]
        favorable = [effect.topic for effect in news.effects if effect.direction > 0]
        st.write(
            "**뉴스 흐름** · "
            + (f"부담: {', '.join(adverse)}" if adverse else "뚜렷한 부담 뉴스 없음")
            + (f" / 우호: {', '.join(favorable)}" if favorable else "")
        )
    else:
        st.caption("새 코인 뉴스의 방향 가정은 현재 조정 설명에 추가되지 않았어요.")
    st.markdown("**다가오는 주요 발표와 시장 예상치**")
    feed = calendar_service(__checkout_signature__).snapshot().feed("calendar")
    events = upcoming_events(feed, now)
    if not events:
        if feed.error:
            st.info(
                "경제 일정·시장 예상치 연결이 지연되고 있어요. 발표 시점과 예상치를 확인할 때까지 발표 시나리오는 보류해요."
            )
        elif feed.loading:
            st.caption("주요 경제 발표 일정을 확인하고 있어요. 가격 분석은 계속 볼 수 있어요.")
        else:
            st.caption(
                "제공된 이번 주 자료에서 확인 가능한 예정 발표가 없어요. 다음 주 일정이나 아직 공개되지 않은 예상치는 만들지 않아요."
            )
        return outlook, None, None
    eligible = [event for event in events if event.at < result.prediction.dates[-1].to_pydatetime()]
    zone = ZoneInfo(timezone)
    selected_key = st.selectbox(
        "주목할 발표",
        [event.key for event in events],
        format_func=lambda key: next(
            f"{event.at.astimezone(zone):%m.%d %H:%M} · {event.label}" for event in events if event.key == key
        ),
        key="release_selected",
    )
    event = next(event for event in events if event.key == selected_key)
    stamp = event.at.astimezone(zone)
    st.markdown(
        '<article class="btc-release-card" aria-label="경제지표 발표">'
        f"<p>{stamp:%m.%d %H:%M} KST · 미국 주요 발표</p><strong>{escape(event.label)}</strong><p>{escape(event.title)}</p>"
        f'<div class="btc-release-values"><span>시장 예상<b>{escape(event.forecast or "미제공")}</b></span><span>이전 발표<b>{escape(event.previous or "미제공")}</b></span></div>'
        f'<p>{escape(release_condition(event))}</p><a href="{escape(event.source_url, quote=True)}" target="_blank" rel="noopener noreferrer">Forex Factory / Fair Economy · 출처 보기 ↗</a></article>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"자료 확인 {feed.updated_at.astimezone(zone):%m.%d %H:%M} KST · 이번 주 공개 일정 · 예상치는 시장 컨센서스이며 실제 발표값은 이 피드에서 제공하지 않아요."
    )
    if event not in eligible:
        st.caption("발표 이후를 살펴볼 예측 구간이 없어 현재 가격 경로에 추가하지 않았어요.")
        return outlook, None, None
    if st.session_state.get("_release_condition_event") != event.key:
        st.session_state["release_condition"] = "neutral"
        st.session_state["_release_condition_event"] = event.key
    condition = (
        st.segmented_control(
            "발표 결과를 가정해 보기",
            ["neutral", "adverse", "favorable"],
            default="neutral",
            format_func={"neutral": "예상 부합", "adverse": "코인에 부담", "favorable": "코인에 우호"}.get,
            key="release_condition",
        )
        or "neutral"
    )
    projection = project_event(result, base, event, now, condition, evidence.pressure)
    if projection is not None:
        st.caption(
            f"선택한 가정의 기본/뉴스 경로 대비 최대 차이 {projection.max_move:.1%} · 현재 지표와 변동성을 이용한 제한된 가정이며 검증된 반응 계수가 아니에요. 발표 이후에만 적용하고 단기 영향은 7일 단위로 감쇠해요."
        )
    else:
        st.caption(
            "예상 부합은 방향을 추가하지 않아요. 예상치와 이전치의 차이를 미래 서프라이즈로 사용하지 않습니다."
        )
    if (
        outlook.window_start is not None
        and outlook.window_start.to_pydatetime() <= event.at <= outlook.window_end.to_pydatetime()
    ):
        st.info(
            "과거 사례의 조정 주의 구간과 이 발표 일정이 겹쳐요. 실제 결과에 따라 움직임이 달라질 수 있어요."
        )
    return outlook, event, projection
