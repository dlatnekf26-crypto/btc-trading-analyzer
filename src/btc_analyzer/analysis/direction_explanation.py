"""Faithful reasons for analogue support, with corroborating/conflicting context.

No new scoring: indicators describe the outlook, and current news retains the
existing explicit price assumption. This never claims calibrated future odds.
"""

from dataclasses import dataclass
import math

from btc_analyzer.analysis.direction_outlook import direction_outlook


@dataclass(frozen=True)
class OutlookReason:
    label: str
    text: str
    tone: str = "neutral"


@dataclass(frozen=True)
class DirectionExplanation:
    title: str
    selection: str
    reasons: tuple[OutlookReason, ...]


def _labels(outlook):
    return "·".join(scenario.label for scenario in outlook.scenarios if scenario.key in outlook.leaders)


def _number(values, key):
    try:
        raw = values.get(key)
        if isinstance(raw, bool):
            return None
        value = float(raw)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _relation(outlook, sign):
    if len(outlook.leaders) != 1 or sign == 0:
        return "neutral"
    expected = 1 if outlook.leaders[0] == "up" else -1 if outlook.leaders[0] == "down" else 0
    return "support" if expected == sign else "conflict"


def explain_direction(result, outlook, values=None, news=None, use_news=True):
    if outlook is None:
        return None
    values = values or {}
    leaders = [scenario for scenario in outlook.scenarios if scenario.key in outlook.leaders]
    if len(leaders) == 1:
        lead = leaders[0]
        runner = max(
            (scenario for scenario in outlook.scenarios if scenario.key != lead.key),
            key=lambda scenario: scenario.share,
        )
        gap = "0.1%p 미만" if outlook.margin < 0.0005 else f"{outlook.margin * 100:.1f}%p"
        title = f"{lead.label} 경로를 더 우세하게 본 근거"
        selection = f"유사 사례 {outlook.cases}개 중 {lead.cases}개가 {lead.label} 경로예요. 닮은 정도를 반영한 비중은 {lead.share:.1%}로, {runner.label} {runner.share:.1%}보다 {gap} 높아요."
        if outlook.margin < 0.1:
            selection += " 차이가 작아 박빙이에요."
    else:
        title = f"{_labels(outlook)}을 공동 우세로 본 근거"
        selection = " · ".join(
            f"{scenario.label} {scenario.share:.1%}({scenario.cases}개)" for scenario in leaders
        )
        selection += "로 비중이 같아 한 방향을 더 유력하다고 좁히기 어려워요."
    similarities = [
        f"{scenario.label} {scenario.similarity:.1f}점"
        for scenario in leaders
        if scenario.similarity is not None
    ]
    reasons = [OutlookReason("선정 근거", selection)]
    reasons.append(
        OutlookReason(
            "닮은 정도",
            "우세 그룹의 가중 평균 유사도: "
            + " · ".join(similarities)
            + " / 100점. 점수는 현재 패턴과 닮은 정도를 나타내요."
            if similarities
            else "유사도 상세값이 없어 점수를 만들지 않았어요.",
        )
    )
    close, ema, hist, rsi = (_number(values, key) for key in ("close", "ema_20", "macd_hist", "rsi"))
    trend = []
    signs = []
    if close is not None and ema is not None and close > 0 and ema > 0:
        sign = 1 if close > ema else -1 if close < ema else 0
        signs.append(sign)
        trend.append(
            f"종가가 20봉 평균(EMA20) {'위' if sign > 0 else '아래' if sign < 0 else '동일'}({close / ema - 1:+.1%})"
        )
    if hist is not None:
        sign = 1 if hist > 0 else -1 if hist < 0 else 0
        signs.append(sign)
        trend.append(f"MACD 탄력이 {'상승' if sign > 0 else '하락' if sign < 0 else '중립'} 쪽")
    relations = [_relation(outlook, sign) for sign in signs]
    if trend:
        tone = "conflict" if "conflict" in relations else "support" if "support" in relations else "neutral"
        conclusion = (
            "우세 전망과 엇갈리는 지표가 있어요."
            if tone == "conflict"
            else "우세 방향과 같은 흐름이에요."
            if tone == "support"
            else "지표만으로 방향을 더 좁히지는 않아요."
        )
        reasons.append(OutlookReason("현재 추세", " · ".join(trend) + ". " + conclusion, tone))
    else:
        reasons.append(
            OutlookReason("현재 추세", "현재 EMA20·MACD 값이 없어 지지·반대 근거를 확인하지 못했어요.")
        )
    if rsi is not None and 0 <= rsi <= 100:
        note = (
            "과열 구간이라 되돌림에 주의해요."
            if rsi >= 70
            else "과매도 구간이라 반등 여지가 있지만 하락이 끝났다고 단정하지 않아요."
            if rsi <= 30
            else "과열·과매도 구간은 아니며 이것만으로 상승·하락을 정하지 않아요."
        )
        reasons.append(
            OutlookReason(
                "RSI 확인", f"RSI {rsi:.1f} · {note}", "caution" if rsi >= 70 or rsi <= 30 else "neutral"
            )
        )
    else:
        reasons.append(
            OutlookReason("RSI 확인", "현재 RSI 자료가 없어 과열·과매도 근거를 추가하지 않았어요.")
        )
    if not use_news:
        news_reason = OutlookReason(
            "뉴스 꺼짐", "뉴스 반영을 껐으므로 우세 방향과 가격 경로에 뉴스 가정을 추가하지 않았어요."
        )
    elif news is None or not news.effects:
        news_reason = OutlookReason(
            "뉴스 확인", "반영 가능한 새 코인 뉴스를 확인하지 못해 뉴스 가격 가정을 추가하지 않았어요."
        )
    else:
        topics = " · ".join(effect.topic for effect in news.effects[:3])
        sign = 1 if news.shift > 1e-10 else -1 if news.shift < -1e-10 else 0
        if sign:
            text = f"{topics}의 제한된 뉴스 가정으로 도착 가격 수준을 {news.shift:+.2%} 조정했어요."
        else:
            text = f"{topics}은 중립·상충 가정으로 방향을 더하지 않고 불확실성을 반영했어요."
        baseline = direction_outlook(result)
        if baseline is not None:
            text += (
                f" 뉴스 반영 전에는 {_labels(baseline)}이 우세했지만 현재는 {_labels(outlook)} 쪽이에요."
                if baseline.leaders != outlook.leaders
                else " 뉴스 반영 전후 우세 방향은 같아요."
            )
        news_reason = OutlookReason("뉴스 가정", text, _relation(outlook, sign))
    reasons.append(news_reason)
    return DirectionExplanation(title, selection, tuple(reasons))
