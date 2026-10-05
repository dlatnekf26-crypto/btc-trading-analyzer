"""Known chart analogues, outcome isolation, gaps and calendar closure."""

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.historical_similarity import find_similar_history
from btc_analyzer.candles import candle_close


def frame_from(close, index, volume=None):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(len(close)) if volume is None else volume,
        },
        index=index,
    )


@pytest.fixture
def analogues():
    rng = np.random.default_rng(21)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, 240)))
    volume = rng.lognormal(4, 0.5, len(close))
    pattern = np.array([100, 103, 99, 97, 95, 92, 94, 93, 97, 96, 98, 100])
    profile = np.array([1, 2, 1, 2, 3, 4, 3, 2, 3, 2, 1, 2])
    for start, scale, outcome in ((20, 1, 0.20), (80, 3, -0.20), (140, 0.5, 0.05)):
        close[start : start + 12] = pattern * scale
        volume[start : start + 12] = profile * scale * 200
        close[start + 12 : start + 19] = pattern[-1] * scale * (1 + np.linspace(outcome / 7, outcome, 7))
    close[-12:] = pattern * 10
    volume[-12:] = profile * 800
    index = pd.date_range("2024-01-01", periods=len(close), freq="D", tz="UTC")
    return frame_from(close, index, volume)


def compare(frame, **kwargs):
    return find_similar_history(
        frame, "1d", candle_close(frame.index[-1], "1d"), 12, 7, min_similarity=99.9, **kwargs
    )


def test_finds_actual_scaled_price_and_volume_analogues_with_mixed_outcomes(analogues):
    report = compare(analogues)
    assert {match.start for match in report.matches} == set(analogues.index[[20, 80, 140]])
    for match in report.matches:
        assert match.similarity == pytest.approx(100)
        assert match.volume_similarity == pytest.approx(100)
        assert match.path[11] == 100
        assert match.observed_until <= report.query_start
    outcomes = {match.start: match.forward_return for match in report.matches}
    assert outcomes[analogues.index[20]] == pytest.approx(0.2)
    assert outcomes[analogues.index[80]] == pytest.approx(-0.2)
    assert outcomes[analogues.index[140]] == pytest.approx(0.05)
    assert report.current_path[-1] == 100


def test_later_returns_do_not_choose_or_score_the_past_matches(analogues):
    before = compare(analogues)
    changed = analogues.copy()
    for start in (20, 80, 140):
        anchor = changed.close.iloc[start + 11]
        changed.iloc[start + 12 : start + 19, :4] *= np.linspace(0.5, 0.8, 7)[:, None]
        assert changed.close.iloc[start + 11] == anchor
    after = compare(changed)
    assert [(m.start, m.similarity) for m in before.matches] == [
        (m.start, m.similarity) for m in after.matches
    ]
    assert [m.forward_return for m in before.matches] != [m.forward_return for m in after.matches]


def test_future_or_unfinished_rows_cannot_change_a_historical_comparison(analogues):
    as_of = candle_close(analogues.index[-1], "1d")
    extra = frame_from([10_000, 100_000], pd.date_range(as_of, periods=2, freq="D"))
    expected = compare(analogues)
    actual = find_similar_history(
        pd.concat([analogues, extra]), "1d", as_of + pd.Timedelta(hours=12), 12, 7, min_similarity=99.9
    )
    assert actual == expected


def test_selected_windows_and_followups_never_overlap_each_other_or_query(analogues):
    report = find_similar_history(
        analogues, "1d", candle_close(analogues.index[-1], "1d"), 12, 7, min_similarity=0
    )
    assert len(report.matches) == 5
    ordered = sorted(report.matches, key=lambda match: match.start)
    for left, right in zip(ordered, ordered[1:]):
        assert left.observed_until <= right.start
    assert all(match.observed_until <= report.query_start for match in ordered)


def test_missing_bar_in_matching_window_or_followup_excludes_that_case(analogues):
    for missing in (25, 34):
        report = compare(analogues.drop(analogues.index[missing]))
        assert analogues.index[20] not in {match.start for match in report.matches}


def test_missing_query_bar_and_delayed_latest_bar_are_explained(analogues):
    as_of = candle_close(analogues.index[-1], "1d")
    with pytest.raises(ValueError, match="빠진 봉"):
        find_similar_history(analogues.drop(analogues.index[-3]), "1d", as_of, 12, 7)
    with pytest.raises(ValueError, match="최신 확정 봉"):
        find_similar_history(analogues.iloc[:-1], "1d", as_of, 12, 7)
    invalid = analogues.copy()
    invalid.iloc[-3, invalid.columns.get_loc("close")] = -10
    with pytest.raises(ValueError, match="빠진 봉"):
        find_similar_history(invalid, "1d", as_of, 12, 7)


@pytest.mark.parametrize("tf,freq,start", [("1w", "W-MON", "2022-01-03"), ("1M", "MS", "2022-01-01")])
def test_calendar_months_and_monday_weeks_are_closed_without_nominal_offsets(tf, freq, start):
    index = pd.date_range(start, periods=30, freq=freq, tz="UTC")
    frame = frame_from(np.full(len(index), 100), index)
    end = candle_close(index[-1], tf)
    unfinished = frame_from([200], pd.DatetimeIndex([end]))
    report = find_similar_history(pd.concat([frame, unfinished]), tf, end + pd.Timedelta(hours=12), 6, 3)
    assert report.query_end == end and report.current_path == (100,) * 6
    assert report.matches and all(match.observed_until <= report.query_start for match in report.matches)
    broken = frame.drop(index[-2])
    with pytest.raises(ValueError, match="빠진 봉"):
        find_similar_history(broken, tf, end, 6, 3)


def test_flat_prices_zero_volume_and_short_history_have_honest_results():
    frame = frame_from(np.ones(80) * 100, pd.date_range("2024-01-01", periods=80, tz="UTC"), np.zeros(80))
    report = compare(frame)
    assert not report.volume_used and report.matches
    assert all(
        m.volume_similarity is None and m.similarity == 100 and m.forward_return == 0 for m in report.matches
    )
    short = compare(frame.tail(12))
    assert not short.matches and short.candidate_count == 0 and short.best_similarity is None
    with pytest.raises(ValueError, match="부족"):
        compare(frame.tail(8))


def test_wrong_direction_is_not_a_high_similarity_match(analogues):
    changed = analogues.copy()
    for start in (20, 80, 140):
        values = changed.close.iloc[start : start + 12].to_numpy()[::-1]
        changed.iloc[start : start + 12, :4] = np.column_stack([values, values * 1.01, values * 0.99, values])
    assert not compare(changed).matches


@pytest.mark.parametrize("window,forward", [(5, 7), (121, 7), (12, 0), (12, 721)])
def test_request_sizes_are_bounded(analogues, window, forward):
    with pytest.raises(ValueError, match="6~120"):
        find_similar_history(analogues, "1d", candle_close(analogues.index[-1], "1d"), window, forward)


def test_fractional_match_count_cannot_bypass_the_result_limit(analogues):
    with pytest.raises(ValueError, match="유사 구간 개수"):
        compare(analogues, max_matches=1.5)
