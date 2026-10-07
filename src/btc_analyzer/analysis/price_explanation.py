"""Explain the displayed price and the actual causal indicator-selection decision."""

from btc_analyzer.analysis.direction_explanation import DirectionExplanation, OutlookReason
from btc_analyzer.analysis.forecast import MIN_CALIBRATION


def explain_price(result, projection, period, quote, outlook=None, direction=None):
    evidence = result.technical
    if evidence is None or result.prediction is None:
        return direction
    prediction = result.prediction
    leaders = (
        [scenario for scenario in outlook.scenarios if scenario.key in outlook.leaders] if outlook else []
    )
    if len(leaders) == 1:
        price = f"{leaders[0].label} 우세 경로 {leaders[0].center[-1]:,.2f} {quote}"
        calculation = "그 방향에 속한 과거 경로를 현재 변동성에 맞춘 뒤 지표/패턴 유사도 비중으로 합쳤어요."
    elif leaders:
        price = "공동 우세라 한 가격으로 좁히지 않았어요"
        calculation = "세 방향의 도착 가격을 함께 확인해 주세요."
    else:
        price = f"{projection.center[-1]:,.2f} {quote}"
        calculation = "유사 사례의 가중 평균 경로에 표본 신뢰도와 현재 변동성을 반영했어요."
    basis = f"확정 종가 {result.history.anchor_price:,.2f} {quote} → {period} 뒤 {price}. {calculation}"
    if not evidence.selected:
        basis = basis.replace("지표/패턴 유사도", "가격 패턴 유사도")
    rows = [OutlookReason("가격 계산", basis)]
    pairs = min(evidence.pairs, MIN_CALIBRATION)
    error = (
        f"최근 완료된 {pairs}쌍의 종점 변화율 오차: 기존 {evidence.pattern_mae:.1%} → 지표 후보 {evidence.technical_mae:.1%}. "
        if evidence.pattern_mae is not None and evidence.technical_mae is not None
        else ""
    )
    if evidence.selected:
        decision = (
            "지표를 반영했어요. "
            + error
            + f"오차가 {(1 - evidence.technical_mae / evidence.pattern_mae):.1%} 작아졌어요. "
            + f"모델 중심선 기준 {evidence.baseline_prediction.center[-1]:,.2f} → {prediction.center[-1]:,.2f} {quote}."
        )
        tone = "support"
    else:
        reason = {
            "few_pairs": f"완료된 비교가 {evidence.pairs}쌍으로 {MIN_CALIBRATION}쌍보다 적어요.",
            "missing": "현재 지표 자료나 준비 기간이 부족해요.",
            "few_matches": "지표까지 닮은 독립 과거 사례가 부족해요.",
            "not_better": "과거 오차가 기존 방식보다 5% 넘게 줄지 않았어요.",
        }[evidence.reason]
        decision = "지표를 검토했지만 가격 보정은 보류했어요. " + reason + " " + error
        tone = "caution"
    rows.append(OutlookReason("지표 반영", decision, tone))
    if direction is not None:
        rows.extend(direction.reasons[:2])
    for group in evidence.groups:
        note = (
            f"선택된 과거 {group.matched_cases}개와 지표 유사도 {group.similarity:.1f}/100점."
            if group.similarity is not None
            else "비교할 지표 자료가 부족해요."
        )
        ready = (
            f" 준비된 지표 {group.ready}/{group.total}개만 검토했어요." if group.ready < group.total else ""
        )
        label = (
            "현재 추세"
            if group.key == "trend" and direction
            else "RSI 확인"
            if group.key == "momentum" and direction
            else group.label
        )
        text = f"{group.label} · {group.summary}. {note}{ready}"
        family_tone = "neutral"
        if direction is not None and group.key in ("trend", "momentum"):
            contextual = direction.reasons[2 if group.key == "trend" else 3]
            text += " " + contextual.text
            family_tone = contextual.tone
        rows.append(OutlookReason(label, text, family_tone))
    if direction is not None:
        rows.append(direction.reasons[-1])
    title = "예상 가격과 우세 방향을 이렇게 계산했어요" if direction else "예상 가격을 이렇게 계산했어요"
    return DirectionExplanation(title, direction.selection if direction else basis, tuple(rows))
