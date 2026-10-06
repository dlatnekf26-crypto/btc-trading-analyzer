"""Correction incidence and release what-ifs stay causal and explicitly conditional."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.analysis.correction import correction_outlook, project_event, technical_evidence
from btc_analyzer.analysis.forecast import ForecastReport, forecast_path
from btc_analyzer.data.economic_calendar import EconomicEvent
from btc_analyzer.ui.correction_view import correction_context
from btc_analyzer.ui.forecast_view import prediction_chart
from test_forecast import mixed_report, prices


def forecast():
    report = mixed_report()
    matches = tuple(
        replace(match, path=(*match.path[: report.window - 1], 100, 99, 97, 94, 90, 92, 95, 96))
        for match in report.matches
    )
    report = replace(report, matches=matches)
    return ForecastReport(report, forecast_path(report), None, (), None, None, None, None)


def test_first_close_breach_window_and_conditional_trough_not_future_probability():
    result = forecast()
    actual = correction_outlook(result)
    assert actual.cases == actual.hits == 3 and actual.share == 1
    assert actual.window_start == result.prediction.dates[2]
    assert actual.window_end == result.prediction.dates[3]
    assert actual.trigger_price == 950
    assert actual.low == pytest.approx(900) and actual.high == pytest.approx(900)
    assert result.validation == () and result.mae is None


def test_fewer_than_two_hits_or_insufficient_cases_have_no_fake_date():
    result = ForecastReport(mixed_report(), forecast_path(mixed_report()), None, (), None, None, None, None)
    actual = correction_outlook(result)
    assert actual.hits == 1 and actual.window_start is None and actual.low is None
    invalid = replace(result, history=replace(result.history, matches=result.history.matches[:2]))
    assert correction_outlook(invalid).share is None
    assert correction_outlook(replace(result, prediction=None)).share is None
    with pytest.raises(ValueError):
        correction_outlook(result, -0.05)


def test_future_outcome_cannot_enter_correction_and_bad_paths_are_rejected():
    result = forecast()
    for match in (
        replace(result.history.matches[0], observed_until=result.history.query_end + pd.Timedelta(days=1)),
        replace(result.history.matches[0], path=(np.nan,) * len(result.history.matches[0].path)),
    ):
        changed = replace(
            result, history=replace(result.history, matches=(match, *result.history.matches[1:]))
        )
        assert correction_outlook(changed).share is None


def test_release_only_changes_conditional_prices_after_release_and_preserves_baseline():
    result = forecast()
    now = result.prediction.dates[0].to_pydatetime()
    event = EconomicEvent("CPI y/y", "CPI", "inflation", now + timedelta(days=2), "2.5%", "3.0%", "High")
    original = result.prediction
    assert project_event(result, original, event, now, "neutral") is None
    for condition, sign in (("adverse", -1), ("favorable", 1)):
        path = project_event(result, original, event, now, condition, pressure=2)
        assert path.center[:3] == original.center[:3]
        assert np.sign(path.center[3] - original.center[3]) == sign
        assert path.max_move < 0.031
        assert all(lo <= center <= hi for lo, center, hi in zip(path.lower, path.center, path.upper))
        assert result.prediction is original and result.mae is None
        # A previous-to-forecast decline is not interpreted as a surprise.
        reverse_consensus = replace(event, forecast="9.0%", previous="1.0%")
        assert project_event(result, original, reverse_consensus, now, condition, 2) == path
    assert project_event(result, original, event, event.at, "adverse") is None
    assert (
        project_event(
            result, original, replace(event, at=result.prediction.dates[-1].to_pydatetime()), now, "adverse"
        )
        is None
    )
    assert (
        project_event(result, original, replace(event, at=now + timedelta(days=90)), now, "adverse") is None
    )


def test_current_and_past_indicators_cannot_read_outcome_candles():
    index = pd.date_range("2024-01-01", periods=150, freq="D", tz="UTC")
    frame = prices(np.linspace(100, 150, len(index)), index)
    origin, matched = index[120], index[70]
    current, past = correction_context(frame, "1d", origin, (matched,))
    assert current["close"] == frame.loc[index[119], "close"]
    assert past[0]["close"] == frame.loc[matched, "close"]
    changed = frame.copy()
    changed.loc[changed.index > matched, ["open", "high", "low", "close"]] *= 10
    assert correction_context(changed, "1d", origin, (matched,))[1] == past
    changed = frame.copy()
    changed.loc[changed.index >= origin, ["open", "high", "low", "close"]] *= 10
    assert correction_context(changed, "1d", origin, (matched,)) == (current, past)
    assert technical_evidence({}).reasons == ()


def test_chart_adds_release_and_timing_without_altering_historical_or_base_traces():
    result = forecast()
    now = result.prediction.dates[0].to_pydatetime()
    event = EconomicEvent("CPI", "CPI", "inflation", now + timedelta(days=2), "2%", "3%", "High")
    projection = project_event(result, result.prediction, event, now, "adverse")
    original = prediction_chart(result, "Asia/Seoul", "USDT")
    changed = prediction_chart(
        result,
        "Asia/Seoul",
        "USDT",
        correction=correction_outlook(result),
        event=event,
        event_projection=projection,
    )
    assert [trace.to_plotly_json() for trace in original.data] == [
        trace.to_plotly_json() for trace in changed.data[:-1]
    ]
    assert changed.data[-1].name == "발표 조건부 경로"
    assert len(changed.layout.shapes) == len(original.layout.shapes) + 2
