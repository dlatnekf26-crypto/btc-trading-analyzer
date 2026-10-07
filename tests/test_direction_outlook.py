"""Directional support, causal guards, missing branches and chart price integrity."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.direction_outlook import direction_outlook
from btc_analyzer.analysis.forecast import ForecastReport, forecast_path
from btc_analyzer.analysis.historical_similarity import HistoricalMatch, SimilarityReport
from btc_analyzer.ui.direction_view import direction_cards, direction_headline
from btc_analyzer.ui.forecast_view import prediction_chart


def result_for(
    returns=(0.10, 0.20, -0.10, -0.80, 0.001), scores=(95, 95, 90, 90, 90), forward=7, volatility=0.01
):
    start = pd.Timestamp("2024-02-01", tz="UTC")
    matches = tuple(
        HistoricalMatch(
            start - pd.Timedelta(days=(forward + 100) * (i + 1)),
            start - pd.Timedelta(days=(forward + 100) * (i + 1) - 3),
            start - pd.Timedelta(days=(forward + 100) * (i + 1) - 3 - forward),
            score,
            score,
            score,
            None,
            tuple(np.r_[100, 100, 100, 100 * np.exp(np.linspace(0, np.log1p(move), forward + 1))]),
            move,
            min(0, move),
            max(0, move),
            volatility,
        )
        for i, (move, score) in enumerate(zip(returns, scores))
    )
    history = SimilarityReport(
        "1d",
        4,
        forward,
        matches[-1].start,
        start,
        start,
        start + pd.Timedelta(days=4),
        (100,) * 4,
        len(matches),
        max(scores),
        False,
        matches,
        1000,
        volatility,
    )
    return ForecastReport(history, forecast_path(history), None, (), None, None, None, None)


def test_weighted_direction_support_selects_group_not_largest_later_move_and_preserves_model():
    result = result_for()
    before = result.prediction
    outlook = direction_outlook(result)
    up, flat, down = outlook.scenarios
    assert outlook.leaders == ("up",) and outlook.margin > 0.1
    assert [scenario.cases for scenario in outlook.scenarios] == [2, 1, 2]
    assert up.share == pytest.approx(sum(before.weights[:2]))
    assert flat.share == pytest.approx(before.weights[4])
    assert sum(scenario.share for scenario in outlook.scenarios) == pytest.approx(1)
    assert up.center[-1] == pytest.approx(1000 * np.sqrt(1.1 * 1.2))
    assert down.center[-1] < 1000 * (1 - outlook.threshold)
    assert abs(flat.center[-1] / 1000 - 1) <= outlook.threshold
    assert all(scenario.center[0] == 1000 for scenario in outlook.scenarios)
    assert result.prediction == before  # No reweighting, band changes or shrinkage in the base model.


def test_missing_directions_are_zero_share_assumptions_and_cannot_win():
    result = result_for((0.1, 0.2, 0.3), (90, 90, 90))
    outlook = direction_outlook(result)
    assert outlook.leaders == ("up",)
    up, flat, down = outlook.scenarios
    assert up.share == pytest.approx(1) and not up.assumed
    for scenario in (flat, down):
        assert scenario.assumed and scenario.cases == 0 and scenario.share == 0
        assert scenario.center[0] == 1000 and np.isfinite(scenario.center).all()
    assert abs(flat.center[-1] / 1000 - 1) <= outlook.threshold + 1e-12
    assert down.center[-1] / 1000 - 1 < -outlook.threshold
    html = direction_cards(outlook, 1000, "<USD>")
    assert html.count("사례 없음 · 선정 제외") == 2 and "&lt;USD&gt;" in html
    assert "100%" in html and "확률" not in html


def test_equal_or_close_support_is_explicit_and_never_forces_a_flat_winner():
    tied = direction_outlook(result_for((0.1, 0, -0.1), (90, 90, 90)))
    assert tied.leaders == ("up", "flat", "down") and tied.margin == pytest.approx(0)
    assert "같아요" in direction_headline(tied)
    close = direction_outlook(result_for((0.1, 0, -0.1), (90.1, 90, 90)))
    assert close.leaders == ("up",) and "박빙" in direction_headline(close)


@pytest.mark.parametrize("forward,volatility", [(7, 0.001), (30, 0.01), (183, 0.08)])
def test_horizon_specific_flat_boundaries_are_inclusive_and_bounded(forward, volatility):
    result = result_for((0.1, 0, -0.1), (90,) * 3, forward, volatility)
    threshold = direction_outlook(result).threshold
    assert 0.005 - 1e-12 <= threshold <= 0.05 + 1e-12
    boundary = direction_outlook(result_for((threshold, -threshold, 0), (90,) * 3, forward, volatility))
    assert boundary.leaders == ("flat",) and boundary.scenarios[1].cases == 3


@pytest.mark.parametrize("change", ["future", "nan", "short", "bad_anchor", "zero_sigma"])
def test_invalid_or_not_completed_analogue_cannot_supply_direction_support(change):
    result = result_for((0.1, 0, -0.1), (90,) * 3)
    match = result.history.matches[0]
    bad = {
        "future": replace(match, observed_until=result.history.query_start + pd.Timedelta(seconds=1)),
        "nan": replace(match, path=(*match.path[:-1], np.nan)),
        "short": replace(match, path=match.path[:-1]),
        "bad_anchor": replace(match, path=tuple(value * 2 for value in match.path)),
        "zero_sigma": replace(match, volatility=0),
    }[change]
    assert (
        direction_outlook(
            replace(result, history=replace(result.history, matches=(bad, *result.history.matches[1:])))
        )
        is None
    )
    assert direction_outlook(replace(result, prediction=None)) is None


def test_current_news_price_assumption_changes_paths_not_weights_and_bad_projection_is_withheld():
    result = result_for((0.001, 0, -0.001), (90,) * 3)
    before = direction_outlook(result)
    factor = np.exp(np.linspace(0, 0.02, 8))
    projection = replace(result.prediction, center=tuple(np.asarray(result.prediction.center) * factor))
    after = direction_outlook(result, projection)
    assert before.leaders == ("flat",) and after.leaders == ("up",)
    assert after.scenarios[0].share == pytest.approx(1)
    assert after.scenarios[0].center[0] == 1000
    assert result.prediction.weights == (1 / 3,) * 3
    assert direction_outlook(result) == before
    assert direction_outlook(result, replace(projection, center=(np.nan,) * 8)) is None


def test_dominant_single_weight_still_cannot_claim_a_direction():
    result = result_for((0.1, 0, -0.1), (90,) * 3)
    assert (
        direction_outlook(replace(result, prediction=replace(result.prediction, weights=(0.98, 0.01, 0.01))))
        is None
    )


def test_comparison_graph_sends_three_branches_highlights_leader_and_preserves_original_model_view():
    result = result_for()
    outlook = direction_outlook(result)
    original = prediction_chart(result, "Asia/Seoul", "USDT")
    comparison = prediction_chart(result, "Asia/Seoul", "USDT", outlook=outlook)
    assert len(comparison.data) == 6
    assert [trace.meta["direction"] for trace in comparison.data[3:]] == ["up", "flat", "down"]
    assert comparison.data[3].line.width > comparison.data[4].line.width
    for scenario, trace in zip(outlook.scenarios, comparison.data[3:]):
        assert trace.y == tuple(np.round(scenario.center, 2))
        assert trace.x == original.data[3].x and trace.y[0] == 1000
    assert comparison.data[0].y == original.data[0].y and comparison.data[1].y == original.data[1].y
    assert original.to_dict() == prediction_chart(result, "Asia/Seoul", "USDT").to_dict()
    assert comparison.layout.dragmode is False and comparison.layout.yaxis.fixedrange
