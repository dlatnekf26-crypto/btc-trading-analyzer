"""Reasons must match selection and include contradicting or missing evidence."""

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pytest

from btc_analyzer.analysis.direction_explanation import explain_direction
from btc_analyzer.analysis.direction_outlook import direction_outlook
from btc_analyzer.analysis.news_projection import NewsEffect, NewsProjection
from btc_analyzer.ui.direction_view import direction_reason_card
from test_direction_outlook import result_for


def news_for(result, shift=0.02, direction=1, topic="BTC 수급"):
    factor = np.exp(np.linspace(0, np.log1p(shift), len(result.prediction.center)))
    center = tuple(np.asarray(result.prediction.center) * factor)
    return NewsProjection(
        center,
        result.prediction.lower,
        result.prediction.upper,
        datetime.now(timezone.utc),
        (NewsEffect(topic, direction, 1, "분류된 뉴스 가정", ("https://example.com/news",)),),
        shift,
        "현재 뉴스",
    )


def by_label(explanation, label):
    return next(reason for reason in explanation.reasons if reason.label == label)


def test_selection_reason_uses_weighted_support_gap_and_exact_group_similarity_without_changing_prices():
    result = result_for()
    outlook = direction_outlook(result)
    before = (result.prediction, outlook)
    explanation = explain_direction(result, outlook, {"close": 110, "ema_20": 100, "macd_hist": 1, "rsi": 55})
    assert "상승" in explanation.title and "5개 중 2개" in explanation.selection
    assert f"{outlook.scenarios[0].share:.1%}" in explanation.selection
    assert f"{outlook.margin * 100:.1f}%p" in explanation.selection
    assert outlook.scenarios[0].similarity == pytest.approx(95)
    assert "상승 95.0점" in by_label(explanation, "닮은 정도").text
    assert by_label(explanation, "현재 추세").tone == "support"
    assert (result.prediction, direction_outlook(result)) == before
    unequal = result_for(scores=(95, 91, 90, 90, 90))
    actual = direction_outlook(unequal).scenarios[0].similarity
    expected = np.average([95, 91], weights=unequal.prediction.weights[:2])
    assert actual == pytest.approx(expected) and actual != pytest.approx(93)


def test_contradictory_or_mixed_indicators_are_reported_instead_of_claiming_confirmation():
    result = result_for()
    for hist in (-1, 1):
        explanation = explain_direction(
            result, direction_outlook(result), {"close": 90, "ema_20": 100, "macd_hist": hist, "rsi": 78}
        )
        trend = by_label(explanation, "현재 추세")
        assert trend.tone == "conflict" and "엇갈리는" in trend.text and "아래" in trend.text
        assert by_label(explanation, "RSI 확인").tone == "caution"
        assert "되돌림" in by_label(explanation, "RSI 확인").text


def test_flat_or_tied_support_does_not_turn_trending_indicators_into_neutral_confirmation():
    result = result_for((0, 0, 0), (90, 90, 90))
    outlook = direction_outlook(result)
    explanation = explain_direction(result, outlook, {"close": 110, "ema_20": 100, "macd_hist": 1})
    assert outlook.leaders == ("flat",) and by_label(explanation, "현재 추세").tone == "conflict"
    tied = result_for((0.1, 0, -0.1), (90, 90, 90))
    explanation = explain_direction(
        tied, direction_outlook(tied), {"close": 110, "ema_20": 100, "macd_hist": 1}
    )
    assert "공동 우세" in explanation.title and "좁히기 어려워요" in explanation.selection
    assert by_label(explanation, "현재 추세").tone == "neutral"
    close = result_for((0.1, 0, -0.1), (90.001, 90, 90))
    explanation = explain_direction(close, direction_outlook(close))
    assert "박빙" in explanation.selection and "0.1%p 미만" in explanation.selection


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"close": None, "ema_20": 0, "macd_hist": np.nan, "rsi": 101},
        {"close": np.inf, "ema_20": "bad", "macd_hist": "bad", "rsi": None},
    ],
)
def test_missing_bad_indicators_do_not_invent_support(values):
    result = result_for()
    explanation = explain_direction(result, direction_outlook(result), values)
    assert by_label(explanation, "현재 추세").tone == "neutral"
    assert "없어" in by_label(explanation, "현재 추세").text
    assert "자료가 없어" in by_label(explanation, "RSI 확인").text


def test_news_toggle_missing_neutral_and_reclassified_winner_have_distinct_reasons():
    result = result_for((0.001, 0, -0.001), (90, 90, 90))
    news = news_for(result)
    active = direction_outlook(result, news)
    explanation = explain_direction(result, active, news=news)
    actual = by_label(explanation, "뉴스 가정")
    assert actual.tone == "support" and "+2.00%" in actual.text
    assert "전에는 보합" in actual.text and "현재는 상승" in actual.text
    disabled = explain_direction(result, direction_outlook(result), news=news, use_news=False)
    assert by_label(disabled, "뉴스 꺼짐").text and "뉴스 가정" not in [
        item.label for item in disabled.reasons
    ]
    missing = explain_direction(result, direction_outlook(result))
    assert "확인하지 못해" in by_label(missing, "뉴스 확인").text
    neutral = news_for(result, 0, 0)
    neutral_reason = by_label(
        explain_direction(result, direction_outlook(result, neutral), news=neutral), "뉴스 가정"
    )
    assert (
        neutral_reason.tone == "neutral"
        and "중립·상충" in neutral_reason.text
        and "우세 방향은 같아요" in neutral_reason.text
    )


def test_news_opposes_leader_and_unsafe_topic_is_escaped_in_reason_card():
    result = result_for()
    news = news_for(result, -0.02, -1, topic="<script>alert(1)</script>")
    outlook = direction_outlook(result, news)
    explanation = explain_direction(result, outlook, news=news)
    assert outlook.leaders == ("up",)
    assert by_label(explanation, "뉴스 가정").tone == "conflict"
    html = direction_reason_card(explanation)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "미래 확률이 아니에요" in html and 'aria-label="우세 방향 이유"' in html


def test_invalid_or_not_completed_match_cannot_change_group_similarity():
    result = result_for()
    bad = replace(result.history.matches[0], observed_until=result.history.query_end, similarity=100)
    filtered = replace(result, history=replace(result.history, matches=(bad, *result.history.matches[1:])))
    outlook = direction_outlook(filtered)
    assert outlook.cases == 4
    assert outlook.scenarios[0].cases == 1 and outlook.scenarios[0].similarity == pytest.approx(95)
    assert outlook.scenarios[2].similarity == pytest.approx(90)
    assert explain_direction(result, None) is None
