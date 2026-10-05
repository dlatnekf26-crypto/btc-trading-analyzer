"""Indicator arithmetic, gap warmups and causal model selection."""

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.forecast import context_evidence, predict_history
from btc_analyzer.analysis.forecast_context import context_indicators
from btc_analyzer.analysis.historical_similarity import prepare_history


def trending_frame(count=100):
    close = np.arange(100, 100 + count, dtype=float)
    return pd.DataFrame(
        {"open": close - 1, "high": close, "low": close - 2, "close": close, "volume": np.ones(count)},
        index=pd.date_range("2020-01-01", periods=count, freq="D", tz="UTC"),
    )


def test_context_has_known_wilder_warmups_and_money_flow_extremes():
    frame = trending_frame()
    values = context_indicators(frame, np.zeros(len(frame)))
    assert np.isnan(values[:14, 0]).all() and (values[14:, 0] == 100).all()
    assert np.isnan(values[:27, 1]).all() and (values[27:, 1] == 100).all()
    assert np.isnan(values[:19, 2]).all() and (values[19:, 2] == 1).all()
    frame["close"] = frame.low
    assert (context_indicators(frame, np.zeros(len(frame)))[19:, 2] == -1).all()
    frame["close"] = (frame.high + frame.low) / 2
    assert (context_indicators(frame, np.zeros(len(frame)))[19:, 2] == 0).all()
    frame["volume"] = 0
    assert np.isnan(context_indicators(frame, np.zeros(len(frame)))[:, 2]).all()


def test_context_is_prefix_invariant_and_restarts_after_missing_candles():
    frame = trending_frame().drop(pd.Timestamp("2020-02-20", tz="UTC"))
    end = frame.index[-1] + pd.Timedelta(days=1)
    prepared = prepare_history(frame, "1d", end, 12, 7)
    values = prepared.context
    gap = 50
    assert np.isnan(values[gap : gap + 14, 0]).all()
    assert np.isnan(values[gap : gap + 27, 1]).all()
    assert np.isnan(values[gap : gap + 19, 2]).all()
    prefix = frame.iloc[:85]
    short = prepare_history(prefix, "1d", prefix.index[-1] + pd.Timedelta(days=1), 12, 7)
    np.testing.assert_allclose(values[:85], short.context, equal_nan=True)
    changed = frame.copy()
    changed.iloc[85:, :4] *= 3
    np.testing.assert_allclose(
        values[:85], prepare_history(changed, "1d", end, 12, 7).context[:85], equal_nan=True
    )


def test_context_gate_needs_twelve_pairs_and_meaningful_improvement():
    assert not context_evidence([(0.1, 0.05)] * 11)[0]
    assert context_evidence([(0.1, 0.05)] * 12)[0]
    assert not context_evidence([(0.1, 0.096)] * 12)[0]
    assert not context_evidence([(0, 0)] * 12)[0]
    assert not context_evidence([(0.1, 0.05)] * 20 + [(0.1, 0.15)] * 12)[0]


def test_validation_does_not_enable_context_until_previous_pairs_are_complete():
    frame = trending_frame(1200)
    rng = np.random.default_rng(87)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(frame))))
    frame["close"], frame["open"] = close, close
    frame["high"], frame["low"] = close * 1.01, close * 0.99
    end = frame.index[-1] + pd.Timedelta(days=1)
    result = predict_history(frame, "1d", end, 12, 7, min_similarity=50, use_context=True)
    assert len(result.validation) == 24
    assert all(case.model == "pattern" for case in result.validation[:12])
    assert result.context_cases >= 12
    # Turn off the feature for a reproducible previous-model benchmark.
    baseline = predict_history(frame, "1d", end, 12, 7, min_similarity=50, use_context=False)
    assert result.validation[:12] == baseline.validation[:12]
    assert all(case.model == "pattern" for case in baseline.validation)
    assert baseline.context_values == ()
    target = result.validation[15]
    changed = frame.copy()
    changed.loc[changed.index >= target.origin, ["open", "high", "low", "close"]] *= 1.7
    after = predict_history(changed, "1d", end, 12, 7, min_similarity=50, use_context=True)
    actual = next(case for case in after.validation if case.origin == target.origin)
    assert actual.model == target.model
    assert actual.predicted_return == pytest.approx(target.predicted_return)
    assert actual.actual_return != target.actual_return


def test_compiled_context_smoothing_matches_the_reference_sma_seeded_wilder():
    from btc_analyzer.analysis.forecast_context import momentum, seeded_wilder
    from btc_analyzer.indicators.core import rsi, wilder

    rng = np.random.default_rng(61)
    series = pd.Series(np.r_[np.full(7, np.nan), rng.uniform(0, 20, 3000)])
    np.testing.assert_allclose(seeded_wilder(series, 14), wilder(series, 14), equal_nan=True, atol=1e-12)
    for close in (pd.Series(np.ones(100)), pd.Series(rng.uniform(50, 100, 3000))):
        np.testing.assert_allclose(momentum(close), rsi(close), equal_nan=True, atol=1e-12)
