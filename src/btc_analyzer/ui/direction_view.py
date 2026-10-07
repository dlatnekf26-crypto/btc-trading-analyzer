"""Compact direction comparison cards for the existing forecast fragment."""

from html import escape


COLORS = {"up": "#079b72", "flat": "#64748b", "down": "#dc5267"}


def direction_cards(outlook, anchor, quote):
    cards = []
    for scenario in outlook.scenarios:
        leading = scenario.key in outlook.leaders
        badge = (
            "공동 우세" if leading and len(outlook.leaders) > 1 else "비중 우세" if leading else "비교 경로"
        )
        if scenario.assumed:
            badge = "조건부 가정"
        movement = scenario.center[-1] / anchor - 1
        cards.append(
            f'<article class="btc-direction-card {scenario.key}{" leading" if leading else ""}" data-direction="{scenario.key}">'
            f"<p><b>{scenario.label}</b><span>{badge}</span></p>"
            f"<strong>{scenario.center[-1]:,.0f}</strong><small>{escape(quote)} · {movement:+.1%}</small>"
            f'<div class="btc-direction-weight">{scenario.share:.0%}<span>가중 비중</span></div>'
            f'<div class="btc-direction-track"><i style="width:{scenario.share * 100:.2f}%"></i></div>'
            f"<small>{f'유사 사례 {scenario.cases}개' if scenario.cases else '사례 없음 · 선정 제외'}</small></article>"
        )
    return '<div class="btc-direction-cards" aria-label="상승 하락 보합 비교">' + "".join(cards) + "</div>"


def direction_headline(outlook):
    leaders = [scenario.label for scenario in outlook.scenarios if scenario.key in outlook.leaders]
    if len(leaders) == 3:
        return "세 방향의 비중이 같아요"
    if len(leaders) > 1:
        return "·".join(leaders) + " 공동 우세"
    return leaders[0] + (" 비중 우세 · 박빙" if outlook.margin < 0.1 else " 비중 우세")


def direction_reason_card(explanation):
    labels = {
        "neutral": "확인 근거",
        "support": "같은 방향",
        "conflict": "엇갈리는 근거",
        "caution": "주의 근거",
    }
    rows = []
    for reason in explanation.reasons:
        tone = reason.tone if reason.tone in labels else "neutral"
        rows.append(
            f'<div class="btc-direction-reason-row {tone}"><span>{escape(reason.label)}<small>{labels[tone]}</small></span><p>{escape(reason.text)}</p></div>'
        )
    return (
        '<article class="btc-direction-reasons" aria-label="우세 방향 이유"><strong>'
        + escape(explanation.title)
        + "</strong>"
        + "".join(rows)
        + "<small>우세 선은 유사 사례 비중으로 선정해요. 현재 지표는 그 전망을 지지하거나 반대하는 참고 근거예요. 비중은 미래 확률이 아니에요.</small></article>"
    )
