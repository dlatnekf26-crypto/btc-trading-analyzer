"""News scenarios cannot alter technical validation or consume future/old headlines."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from btc_analyzer.analysis.forecast import ForecastReport, forecast_path
from btc_analyzer.analysis.news_projection import project_news
from btc_analyzer.data.market_context import FeedState, MarketContext, NewsItem, classify_headline
from btc_analyzer.ui.forecast_view import prediction_chart
from test_forecast import mixed_report


@pytest.fixture
def result():
    history = mixed_report()
    return ForecastReport(history, forecast_path(history), None, (), None, None, None, None)


def article(result, title, hours=1):
    now = result.prediction.dates[0].to_pydatetime() + timedelta(hours=12)
    topic, direction, uncertainty, explanation, pending = classify_headline(title)
    return NewsItem(
        "Bitcoin market: " + title,
        "https://news.google.com/rss/articles/" + str(len(title)),
        "Example",
        now - timedelta(hours=hours),
        topic,
        direction,
        uncertainty,
        explanation,
        pending,
    )


def projection(result, items, updated_age=0):
    now = result.prediction.dates[0].to_pydatetime() + timedelta(hours=12)
    context = MarketContext((FeedState("news_ko", tuple(items), now - timedelta(minutes=updated_age)),))
    return project_news(result, context, now)


@pytest.mark.parametrize(
    "title,sign", [("Oil surges", -1), ("Fed cuts rates", 1), ("CPI preview ahead of release", 0)]
)
def test_news_direction_changes_only_scenario_and_all_paths_share_anchor(result, title, sign):
    before = result.prediction
    actual = projection(result, [article(result, title)])
    assert np.sign(actual.shift) == sign
    assert actual.center[0] == actual.lower[0] == actual.upper[0] == result.history.anchor_price
    assert all(lo <= center <= hi for lo, center, hi in zip(actual.lower, actual.center, actual.upper))
    assert all(lo <= base for lo, base in zip(actual.lower, before.lower))
    assert all(hi >= base for hi, base in zip(actual.upper, before.upper))
    if sign == 0:
        assert actual.center == before.center and actual.lower[-1] < before.lower[-1]
    assert result.prediction is before and result.validation == () and result.mae is None
    original = prediction_chart(result, "Asia/Seoul", "USDT")
    changed = prediction_chart(result, "Asia/Seoul", "USDT", news_projection=actual)
    assert len(changed.data) == 11
    for a, b in zip(original.data, changed.data[:5]):
        assert a.to_plotly_json() == b.to_plotly_json()
    assert changed.data[7].name == "뉴스 반영 시나리오"


def test_before_origin_future_old_and_stale_feed_cannot_adjust_forecast(result):
    old = article(result, "Oil surges", hours=13)
    future = article(result, "Fed cuts rates", hours=-1)
    for items, age in (([old, future], 0), ([article(result, "Oil surges")], 11)):
        actual = projection(result, items, age)
        assert actual.effects == () and actual.center == result.prediction.center


def test_generic_macro_news_without_coin_connection_cannot_adjust_price(result):
    generic = replace(article(result, "Fed cuts rates"), title="Fed cuts rates")
    actual = projection(result, [generic])
    assert actual.effects == () and actual.center == result.prediction.center


def test_syndication_and_conflicting_same_topic_do_not_multiply_shocks(result):
    item = article(result, "Oil surges")
    single = projection(result, [item])
    many = projection(
        result,
        [
            replace(
                item,
                title=f"Bitcoin market: Oil surges, report {i}",
                url=f"https://news.google.com/rss/articles/{i}",
            )
            for i in range(20)
        ],
    )
    assert single.center == many.center and single.lower == many.lower and len(many.effects) == 1
    conflict = projection(result, [item, article(result, "Oil falls")])
    assert conflict.shift == 0 and conflict.center == result.prediction.center
    assert conflict.lower[-1] < result.prediction.lower[-1]
    assert "상반된" in conflict.effects[0].explanation


def test_large_volatility_cannot_create_unbounded_news_shock(result):
    result = replace(result, history=replace(result.history, volatility=1.0))
    actual = projection(
        result,
        [
            article(result, title)
            for title in (
                "Oil surges",
                "Fed hikes rates",
                "CPI higher than expected",
                "Missile attack escalates war",
                "Bitcoin ETF outflows",
            )
        ],
    )
    assert -0.041 <= actual.shift < 0
    assert np.array(actual.center) / result.prediction.center == pytest.approx(
        np.clip(np.array(actual.center) / result.prediction.center, np.exp(-0.04), np.exp(0.04))
    )


def test_same_news_snapshot_keeps_projection_identical_during_case_click(result):
    now = result.prediction.dates[0].to_pydatetime() + timedelta(hours=12)
    context = MarketContext((FeedState("news_ko", (article(result, "Oil surges"),), now),))
    before = project_news(result, context, now)
    after = project_news(result, context, now + timedelta(seconds=10))
    assert before == after


def test_a_newer_neutral_headline_does_not_refresh_an_older_directional_shock(result):
    item = article(result, "Fed cuts rates", hours=8)
    neutral = article(result, "Fed preview ahead of release", hours=1)
    before = projection(result, [item])
    after = projection(result, [item, neutral])
    assert before.center == after.center
    assert after.effects[0].explanation == item.explanation
