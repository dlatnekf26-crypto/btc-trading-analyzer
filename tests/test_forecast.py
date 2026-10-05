"""Forecast anchors, weak-sample guards and genuinely causal validation."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.forecast import forecast_path, predict_history
from btc_analyzer.analysis.historical_similarity import find_similar_history
from btc_analyzer.candles import candle_close, candle_shift


def prices(close, index):
    close = np.array(close, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(len(close)),
        },
        index=index,
    )


def mixed_report():
    pattern = np.array([100, 103, 99, 97, 95, 92, 94, 93, 97, 96, 98, 100])
    close = 100 * np.exp(np.cumsum(np.random.default_rng(21).normal(0, 0.015, 240)))
    for start, scale, outcome in ((20, 1, 0.2), (80, 3, -0.2), (140, 0.5, 0.05)):
        close[start : start + 12] = pattern * scale
        close[start + 12 : start + 19] = pattern[-1] * scale * (1 + np.linspace(outcome / 7, outcome, 7))
    close[-12:] = pattern * 10
    frame = prices(close, pd.date_range("2024-01-01", periods=240, freq="D", tz="UTC"))
    return find_similar_history(frame, "1d", candle_close(frame.index[-1], "1d"), 12, 7, min_similarity=99.9)


def test_mixed_outcomes_become_an_absolute_forecast_with_shrinkage_and_uncertainty():
    report = mixed_report()
    predicted = forecast_path(report)
    assert predicted is not None and predicted.effective_cases == pytest.approx(3)
    assert predicted.weights == pytest.approx([1 / 3] * 3)
    assert predicted.center[0] == predicted.lower[0] == predicted.upper[0] == 1000
    expected = 1000 * np.exp(0.425 * np.mean(np.log([1.2, 0.8, 1.05])))
    assert predicted.center[-1] == pytest.approx(expected)
    assert predicted.lower[-1] <= 800 + 1e-9 and predicted.upper[-1] >= 1200 - 1e-9
    assert predicted.rising_share == pytest.approx(2 / 3)
    assert all(
        lo <= center <= hi for lo, center, hi in zip(predicted.lower, predicted.center, predicted.upper)
    )
    assert predicted.dates[-1] == report.query_end + pd.Timedelta(days=7)


def test_small_or_one_dominant_analogue_cannot_claim_a_prediction():
    report = mixed_report()
    assert forecast_path(replace(report, matches=report.matches[:2])) is None
    dominated = tuple(replace(m, similarity=100 if i == 0 else 10) for i, m in enumerate(report.matches))
    assert forecast_path(replace(report, matches=dominated)) is None


def test_error_calibration_needs_twelve_completed_predictions_and_can_widen_each_step():
    report = mixed_report()
    errors = [np.r_[0, np.full(7, 0.8)]] * 12
    short = forecast_path(report, errors[:11])
    full = forecast_path(report, errors)
    assert short.calibrated_cases == 0 and full.calibrated_cases == 12
    assert full.lower[-1] < short.lower[-1] and full.upper[-1] > short.upper[-1]
    assert full.lower[0] == full.upper[0] == report.anchor_price


@pytest.mark.parametrize("tf,freq", [("1w", "W-MON"), ("1M", "MS")])
def test_future_dates_follow_actual_week_and_month_boundaries(tf, freq):
    frame = prices(np.full(110, 100), pd.date_range("2017-01-01", periods=110, freq=freq, tz="UTC"))
    result = predict_history(frame, tf, candle_close(frame.index[-1], tf), 6, 3)
    assert result.prediction is not None
    assert result.prediction.dates == tuple(candle_shift(result.history.query_end, tf, i) for i in range(4))
    assert result.prediction.center == (100,) * 4


def test_flat_market_does_not_report_fake_directional_accuracy_and_validation_is_disjoint():
    frame = prices(np.full(1200, 100), pd.date_range("2020-01-01", periods=1200, freq="D", tz="UTC"))
    result = predict_history(frame, "1d", candle_close(frame.index[-1], "1d"), 12, 7)
    assert len(result.validation) == 24
    assert result.mae == result.baseline_mae == 0 and result.directional_accuracy is None
    assert result.coverage == 1 and result.prediction.calibrated_cases == 24
    assert all(a.observed_until <= b.origin for a, b in zip(result.validation, result.validation[1:]))
    assert result.validation[11].calibration_cases == 0
    assert result.validation[12].calibration_cases == 12


def test_mutating_later_outcomes_cannot_change_an_earlier_forecast_or_its_band():
    close = 100 * np.exp(np.cumsum(np.random.default_rng(12).normal(0, 0.008, 1200)))
    frame = prices(close, pd.date_range("2020-01-01", periods=1200, freq="D", tz="UTC"))
    end = candle_close(frame.index[-1], "1d")
    before = predict_history(frame, "1d", end, 12, 7, min_similarity=50)
    assert len(before.validation) >= 13
    target = before.validation[12]
    changed = frame.copy()
    changed.loc[changed.index >= target.origin, ["open", "high", "low", "close"]] *= 1.7
    after = predict_history(changed, "1d", end, 12, 7, min_similarity=50)
    actual = next(case for case in after.validation if case.origin == target.origin)
    assert actual.predicted_return == target.predicted_return
    assert actual.lower_return == target.lower_return and actual.upper_return == target.upper_return
    assert actual.calibration_cases == target.calibration_cases
    assert actual.actual_return != target.actual_return
    assert all(case.observed_until <= before.history.query_end for case in before.validation)
    assert before.mae == pytest.approx(
        np.mean([abs(c.predicted_return - c.actual_return) for c in before.validation])
    )
    assert before.baseline_mae == pytest.approx(np.mean([abs(c.actual_return) for c in before.validation]))


def test_not_enough_analogues_withholds_forecast_and_stale_or_missing_data_is_not_filled():
    frame = prices(np.full(30, 100), pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC"))
    end = candle_close(frame.index[-1], "1d")
    result = predict_history(frame, "1d", end, 12, 7)
    assert result.prediction is None and "3개" in result.reason and not result.validation
    with pytest.raises(ValueError, match="최신 확정 봉"):
        predict_history(frame.iloc[:-1], "1d", end, 12, 7)
    with pytest.raises(ValueError, match="빠진 봉"):
        predict_history(frame.drop(frame.index[-2]), "1d", end, 12, 7)


def test_unfinished_and_future_rows_cannot_change_prediction_or_validation():
    frame = prices(np.full(1000, 100), pd.date_range("2020-01-01", periods=1000, freq="D", tz="UTC"))
    end = candle_close(frame.index[-1], "1d")
    extra = prices([10_000, 100_000], pd.date_range(end, periods=2, freq="D"))
    before = predict_history(frame, "1d", end, 12, 7)
    after = predict_history(pd.concat([frame, extra]), "1d", end + pd.Timedelta(hours=12), 12, 7)
    assert after == before


@pytest.mark.parametrize(
    "origin,horizon,target",
    [
        ("2024-01-31", "1mo", "2024-02-29"),
        ("2023-01-31", "1mo", "2023-02-28"),
        ("2024-08-31", "6mo", "2025-02-28"),
        ("2024-02-29", "1y", "2025-02-28"),
        ("2023-03-01", "1y", "2024-03-01"),
        ("2026-12-29", "1w", "2027-01-05"),
    ],
)
def test_quick_horizon_uses_calendar_months_and_leap_years(origin, horizon, target):
    from btc_analyzer.analysis.forecast import horizon_days

    origin = pd.Timestamp(origin, tz="UTC")
    assert origin + pd.Timedelta(days=horizon_days(origin, horizon)) == pd.Timestamp(target, tz="UTC")


def test_vectorized_weighted_quantiles_match_independent_column_interpolation():
    from btc_analyzer.analysis.forecast import weighted_path_quantiles

    rng = np.random.default_rng(321)
    values = rng.normal(size=(5, 366))
    weights = np.array([0.02, 0.14, 0.27, 0.11, 0.46])
    quantiles = (0, 0.1, 0.5, 0.9, 1)
    expected = []
    for q in quantiles:
        row = []
        for column in values.T:
            ranked = sorted(zip(column, weights))
            sorted_values, sorted_weights = map(np.array, zip(*ranked))
            cumulative = np.cumsum(sorted_weights) - sorted_weights / 2
            row.append(np.interp(q, cumulative, sorted_values))
        expected.append(row)
    np.testing.assert_allclose(weighted_path_quantiles(values, weights, quantiles), expected, atol=1e-14)


def test_one_year_forecast_is_complete_and_validation_observes_only_closed_history():
    from btc_analyzer.analysis.forecast import horizon_days

    frame = prices(np.full(3000, 100), pd.date_range(end="2024-02-28", periods=3000, freq="D", tz="UTC"))
    end = candle_close(frame.index[-1], "1d")
    forward = horizon_days(end, "1y")
    result = predict_history(frame, "1d", end, 30, forward)
    assert result.prediction is not None
    assert len(result.prediction.center) == forward + 1
    assert result.prediction.dates[-1] == pd.Timestamp("2025-02-28", tz="UTC")
    assert len(result.validation) < 12  # A long horizon cannot invent more independent evidence.
    assert all(case.observed_until <= end for case in result.validation)
    assert result.prediction.calibrated_cases == 0
