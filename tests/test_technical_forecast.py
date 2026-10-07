"""All indicator families, honest model gates and genuinely causal price reasons."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.direction_explanation import explain_direction
from btc_analyzer.analysis.direction_outlook import direction_outlook
from btc_analyzer.analysis.forecast import predict_history
from btc_analyzer.analysis.historical_similarity import prepare_history
from btc_analyzer.analysis.price_explanation import explain_price
from btc_analyzer.analysis.technical_matching import FAMILIES
from btc_analyzer.candles import candle_close
from btc_analyzer.ui.direction_view import direction_reason_card


def market(seed=0, count=1500):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, count)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        dict(
            open=open_,
            high=np.maximum(close, open_) * 1.01,
            low=np.minimum(close, open_) * 0.99,
            close=close,
            volume=rng.lognormal(2, 0.5, count),
        ),
        index=pd.date_range("2020-01-01", periods=count, freq="D", tz="UTC"),
    )


def forecast(frame, forward=7, **kwargs):
    return predict_history(
        frame,
        "1d",
        candle_close(frame.index[-1], "1d"),
        30,
        forward,
        min_similarity=50,
        use_technical=True,
        **kwargs,
    )


def test_every_family_is_causal_price_unit_independent_and_restarts_at_gaps():
    frame = market(count=400)
    prepared = prepare_history(frame, "1d", candle_close(frame.index[-1], "1d"), 30, 7)
    prefix = frame.iloc[:300]
    short = prepare_history(prefix, "1d", candle_close(prefix.index[-1], "1d"), 30, 7)
    scaled = frame.copy()
    scaled[["open", "high", "low", "close"]] *= 1000
    other = prepare_history(scaled, "1d", candle_close(frame.index[-1], "1d"), 30, 7)
    assert len(prepared.technical.arrays) == 5
    for long_values, short_values, scaled_values in zip(
        prepared.technical.arrays, short.technical.arrays, other.technical.arrays
    ):
        np.testing.assert_allclose(long_values[:300], short_values, equal_nan=True, atol=1e-10)
        np.testing.assert_allclose(long_values, scaled_values, equal_nan=True, atol=1e-10)
    broken = frame.drop(frame.index[220])
    gap = prepare_history(broken, "1d", candle_close(frame.index[-1], "1d"), 30, 7).technical
    assert np.isnan(gap.features.ema_200.iloc[220:]).all()
    assert np.isnan(gap.features.ichimoku_cloud_position.iloc[220:297]).all()
    assert np.isnan(gap.features.rsi.iloc[220:234]).all()


def test_families_have_equal_weight_and_missing_metrics_never_become_neutral_agreement():
    frame = market(count=400)
    technical = prepare_history(frame, "1d", candle_close(frame.index[-1], "1d"), 30, 7).technical
    technical.arrays = [np.zeros_like(values) for values in technical.arrays]
    technical.arrays[0][:30] = 1
    scores, groups = technical.scores(399, 30)
    assert scores[0] == pytest.approx((4 * 100 + 100 * np.exp(-1)) / 5)
    assert groups[0, 0] == pytest.approx(100 * np.exp(-1))
    technical._cache = None
    technical.arrays[3][399] = np.nan
    scores, groups = technical.scores(399, 30)
    assert np.isnan(groups[:, 3]).all()
    assert scores[0] == pytest.approx((3 * 100 + 100 * np.exp(-1)) / 4)
    technical._cache = None
    technical.arrays[1][:30] = np.nan
    assert np.isnan(technical.scores(399, 30)[0][0])


def test_indicator_selection_changes_real_matches_weights_and_price_only_after_completed_evidence():
    frame = market()
    result = forecast(frame)
    original = predict_history(frame, "1d", result.history.query_end, 30, 7, min_similarity=50)
    evidence = result.technical
    assert result.model == "technical" and evidence.selected and evidence.reason == "selected"
    assert evidence.pairs == 24 and evidence.technical_mae < evidence.pattern_mae * 0.95
    assert result.prediction.center[-1] != original.prediction.center[-1]
    assert result.history.matches != original.history.matches
    assert all(match.technical_similarity is not None for match in result.history.matches)
    assert all(case.model == "pattern" for case in result.validation[:12])
    assert result.validation[:12] == original.validation[:12]
    assert (
        result.prediction.center[0]
        == result.prediction.lower[0]
        == result.prediction.upper[0]
        == result.history.anchor_price
    )
    assert all(
        lo <= mid <= hi
        for lo, mid, hi in zip(result.prediction.lower, result.prediction.center, result.prediction.upper)
    )
    assert evidence.baseline_prediction.center == original.prediction.center
    assert tuple(group.key for group in evidence.groups) == tuple(family[0] for family in FAMILIES)


def test_worse_candidate_and_insufficient_six_month_history_keep_original_price():
    for frame, forward, reason in ((market(1), 7, "not_better"), (market(), 183, "few_pairs")):
        result = forecast(frame, forward)
        assert result.model == "pattern" and not result.technical.selected
        assert result.technical.reason == reason
        assert result.prediction.center == result.technical.baseline_prediction.center
        assert not result.history.technical_used


def test_later_outcomes_cannot_select_indicators_or_alter_an_earlier_price_and_band():
    frame = market()
    before = forecast(frame)
    target = before.validation[15]
    changed = frame.copy()
    changed.loc[changed.index >= target.origin, ["open", "high", "low", "close"]] *= 1.7
    after = forecast(changed)
    actual = next(case for case in after.validation if case.origin == target.origin)
    assert (
        actual.model,
        actual.predicted_return,
        actual.lower_return,
        actual.upper_return,
        actual.calibration_cases,
    ) == (
        target.model,
        target.predicted_return,
        target.lower_return,
        target.upper_return,
        target.calibration_cases,
    )
    assert actual.actual_return != target.actual_return
    unfinished = frame.iloc[-2:].copy()
    unfinished.index = pd.date_range(before.history.query_end, periods=2, freq="D")
    unfinished[["open", "high", "low", "close"]] *= 20
    appended = predict_history(
        pd.concat([frame, unfinished]),
        "1d",
        before.history.query_end + pd.Timedelta(hours=12),
        30,
        7,
        min_similarity=50,
        use_technical=True,
    )
    assert appended == before


def test_missing_volume_and_short_cloud_warmup_are_disclosed_without_invented_metrics():
    frame = market()
    frame["volume"] = 0
    result = forecast(frame)
    volume = next(group for group in result.technical.groups if group.key == "volume")
    assert volume.ready == 0 and volume.similarity is None and volume.matched_cases == 0
    assert dict(result.technical.current_values)["cmf"] is None
    assert not result.history.volume_used


def test_price_reasons_use_actual_displayed_price_gate_errors_groups_and_escape_html():
    result = forecast(market())
    outlook = direction_outlook(result)
    direction = explain_direction(result, outlook, dict(result.technical.current_values), use_news=False)
    explained = explain_price(result, result.prediction, "1주", "USDT", outlook, direction)
    rendered = direction_reason_card(explained, price=True)
    assert 'data-price-reasons="true"' in rendered
    assert "지표를 반영했어요" in rendered and "모델 중심선 기준" in rendered
    assert f"{result.technical.pattern_mae:.1%}" in rendered
    assert f"{result.technical.technical_mae:.1%}" in rendered
    assert all(group.label in rendered for group in result.technical.groups)
    assert f"{next(s for s in outlook.scenarios if s.key == outlook.leaders[0]).center[-1]:,.2f}" in rendered
    malformed = replace(
        result.technical,
        groups=(
            replace(result.technical.groups[0], summary="<script>oops</script>"),
            *result.technical.groups[1:],
        ),
    )
    safe = direction_reason_card(
        explain_price(replace(result, technical=malformed), result.prediction, "1주", "USDT"),
        price=True,
        comparison=False,
    )
    assert "&lt;script&gt;" in safe and "<script>" not in safe
    held = forecast(market(1))
    card = explain_price(held, held.prediction, "1주", "USDT")
    assert "보류" in card.reasons[1].text and "5% 넘게 줄지" in card.reasons[1].text


def test_legacy_research_and_full_technical_modes_cannot_be_silently_combined():
    with pytest.raises(ValueError, match="한 방식씩"):
        forecast(market(), use_context=True)
