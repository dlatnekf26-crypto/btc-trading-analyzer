"""Five-horizon decisions, missing history, calendar closure and future isolation."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.candles import candle_close
from btc_analyzer.config import AppConfig, COMPOSITE_TIMEFRAMES
from btc_analyzer.analysis.multi_timeframe import prepare
from btc_analyzer.data.base_provider import normalize, DataError
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.storage.database import Database, dumps
from btc_analyzer.strategy.composite import composite_signal, FRAME_WEIGHTS
from btc_analyzer.strategy.position_view import net_ladder_rr

AS_OF = pd.Timestamp("2026-10-04T12:00Z")


def scenario(sign=1):
    bundle = {}
    for tf in COMPOSITE_TIMEFRAMES:
        rule = {"1h": "h", "4h": "4h", "1d": "D", "1w": "W-MON", "1M": "MS"}[tf]
        index = pd.date_range(end=AS_OF.normalize(), periods=272, freq=rule, name="timestamp")
        index = index[candle_close(index, tf) <= AS_OF][-(100 if tf == "1M" else 270) :]
        if tf in ("1h", "4h"):
            index += AS_OF - candle_close(index[-1], tf)
        x = np.arange(len(index))
        close = 100 * np.exp(sign * 0.002 * x + 0.015 * np.sin(x / 4 + 7))
        opening = np.r_[close[0], close[:-1]]
        bundle[tf] = pd.DataFrame(
            {
                "open": opening,
                "high": np.maximum(opening, close) + close * 0.004,
                "low": np.minimum(opening, close) - close * 0.004,
                "close": close,
                "volume": 100.0,
            },
            index=index,
        )
        bundle[tf].iloc[-1, 4] = 180
        bundle[tf].attrs["timeframe"] = tf
    return bundle


def pullback_scenario():
    bundle = scenario()
    tail = np.r_[
        np.linspace(120, 100, 20),
        100
        + np.array(
            [-1, -2, -1, 0, 1, 2, 3, 2, 1, 0.5, 0, -0.2, -0.3, -0.4, -0.45, -0.5, -0.52, -0.54, -0.55, -0.56]
        ),
    ]
    for tf in ("1d", "4h"):
        frame = bundle[tf]
        close = np.r_[np.linspace(80, 120, len(frame) - 40), tail]
        opening = np.r_[close[0], close[:-1]]
        frame["close"], frame["open"] = close, opening
        frame["high"] = np.maximum(opening, close) + close * 0.004
        frame["low"] = np.minimum(opening, close) - close * 0.004
    bundle["1h"] = scenario(-1)["1h"]
    for tf in ("1h", "1w", "1M"):
        frame = bundle[tf]
        frame.loc[:, ["open", "high", "low", "close"]] *= 99.44 / frame.close.iloc[-1]
    return bundle


def test_pullback_buy_before_bullish_short_term_alignment_requires_daily_rr():
    bundle = pullback_scenario()
    signal = composite_signal(bundle, AS_OF)
    assert signal.action == "매수" and signal.eligible
    assert signal.mode == "눌림목 분할매수"
    assert all(signal.frames[tf].score < 40 for tf in ("1h", "4h", "1d"))
    assert bundle["1d"].close.iloc[-1] < bundle["1d"].close.iloc[-2]
    assert signal.position.discount_pct > 0 and signal.position.stability_score >= 60
    assert signal.plan.entry_low <= signal.position.price <= signal.plan.entry_high
    assert net_ladder_rr(signal.plan, AppConfig()) >= AppConfig().strategy.min_rr
    strict = replace(AppConfig(), strategy=replace(AppConfig().strategy, min_rr=5))
    rejected = composite_signal(bundle, AS_OF, strict)
    assert rejected.action == "관망" and not rejected.eligible
    assert any("RR" in reason for reason in rejected.reasons)


def test_price_discount_during_active_crash_does_not_create_buy():
    bundle = pullback_scenario()
    bundle["1h"].loc[:, ["open", "high", "low", "close"]] *= 0.85
    signal = composite_signal(bundle, AS_OF)
    assert signal.position.value_score >= 65 and signal.position.falling_fast
    assert signal.action == "관망" and signal.plan is None


def test_cheap_price_without_momentum_stabilization_stays_hold():
    bundle = pullback_scenario()
    for tf in ("1d", "4h"):
        frame = bundle[tf]
        close = frame.close.to_numpy().copy()
        close[-5:] = [102, 101.5, 100.9, 100.2, 99.44]
        opening = np.r_[close[0], close[:-1]]
        frame["close"], frame["open"] = close, opening
        frame["high"] = np.maximum(opening, close) + close * 0.004
        frame["low"] = np.minimum(opening, close) - close * 0.004
    signal = composite_signal(bundle, AS_OF)
    assert signal.position.value_score >= 65 and signal.position.stability_score < 60
    assert signal.action == "관망"


def test_support_break_vetoes_buy_even_without_fast_crash():
    bundle = pullback_scenario()
    bundle["1h"].loc[:, ["open", "high", "low", "close"]] *= 96.5 / 99.44
    signal = composite_signal(bundle, AS_OF)
    assert signal.position.broken_support and not signal.position.falling_fast
    assert signal.action == "관망"


def test_bullish_direction_alone_does_not_force_buy_when_daily_net_rr_is_poor():
    signal = composite_signal(scenario(), AS_OF)
    assert signal.agreement == 5 and signal.score.overall >= 65
    assert signal.action == "관망" and any("비용 후 RR" in r for r in signal.reasons)


def test_discount_in_bearish_macro_view_is_risk_reduction_not_buy():
    bundle = pullback_scenario()
    bearish = scenario(-1)
    bundle.update({tf: bearish[tf] for tf in ("1w", "1M")})
    signal = composite_signal(bundle, AS_OF)
    assert signal.position.value_score >= 65
    assert signal.action == "매도" and signal.mode == "중장기 위험 축소"


def test_hourly_low_volume_does_not_veto_medium_term_pullback():
    bundle = pullback_scenario()
    bundle["1h"].iloc[-1, 4] = 1
    assert composite_signal(bundle, AS_OF).action == "매수"
    bundle["1d"].iloc[-1, 4] = 1
    assert composite_signal(bundle, AS_OF).action == "관망"


def test_overheated_uptrend_can_take_partial_profit_before_direction_turns():
    bundle = scenario()
    for frame in bundle.values():
        x = np.arange(len(frame))
        close = 100 * np.exp(0.002 * x + 0.015 * np.sin(x / 4 + 1))
        opening = np.r_[close[0], close[:-1]]
        frame["close"], frame["open"] = close, opening
        frame["high"] = np.maximum(opening, close) + close * 0.004
        frame["low"] = np.minimum(opening, close) - close * 0.004
    signal = composite_signal(bundle, AS_OF)
    assert signal.frames["1d"].score > 60 and signal.position.overheated
    assert signal.action == "매도" and signal.mode == "과열 분할매도"


def test_pullback_plan_targets_are_observed_references_and_costs_can_veto():
    bundle = pullback_scenario()
    signal = composite_signal(bundle, AS_OF)
    assert signal.plan.targets[-1] == bundle["1d"].tail(90).high.max()
    expensive = replace(AppConfig(), risk=replace(AppConfig().risk, fee=0.03, slippage=0.02))
    assert composite_signal(bundle, AS_OF, expensive).action == "관망"


def test_transient_hourly_bounce_does_not_cancel_macro_risk_reduction():
    bundle = scenario(-1)
    bundle["1h"] = scenario()["1h"]
    signal = composite_signal(bundle, AS_OF)
    assert signal.frames["1h"].score > 60 and signal.action == "매도"


def test_sell_is_spot_reduction_without_enabling_shorts():
    signal = composite_signal(scenario(-1), AS_OF)
    assert not AppConfig().strategy.allow_short
    assert signal.action == "매도" and signal.direction == "sell" and signal.eligible
    assert signal.score.overall <= 35
    assert any("현물 보유분 축소" in reason for reason in signal.reasons)


def test_macro_conflict_vetoes_short_term_buy():
    bundle = scenario()
    bearish = scenario(-1)
    bundle.update({tf: bearish[tf] for tf in ("1w", "1M")})
    signal = composite_signal(bundle, AS_OF)
    assert signal.frames["1h"].score > 60
    assert signal.frames["1w"].score < 40
    assert signal.action == "관망"


def test_monthly_partial_history_uses_real_indicators_without_ema200():
    signal = composite_signal(scenario(), AS_OF)
    frame = signal.frames["1M"]
    assert frame.ready and frame.bars == 100
    assert frame.indicators["ema_200"] is None
    assert frame.indicators["sma_200"] is None
    assert frame.indicators["macd_hist"] is not None
    assert frame.indicators["rsi"] is not None
    assert 0 < frame.coverage < 1
    assert "ema_200" in frame.missing
    assert signal.quality < 100
    json.loads(dumps(signal))


def test_monthly_ichimoku_cloud_requires_actual_warmup():
    bundle = scenario()
    bundle["1M"] = bundle["1M"].tail(50)
    signal = composite_signal(bundle, AS_OF)
    monthly = signal.frames["1M"]
    assert monthly.indicators["rsi"] is not None
    assert monthly.indicators["macd_hist"] is not None
    assert monthly.indicators["ichimoku_cloud_b"] is None
    assert not monthly.ready and signal.ready_frames == 4
    assert signal.action == "관망"


@pytest.mark.parametrize("tf", COMPOSITE_TIMEFRAMES)
def test_missing_horizon_vetoes_and_retains_fixed_weights(tf):
    bundle = scenario()
    bundle.pop(tf)
    signal = composite_signal(bundle, AS_OF)
    assert signal.action == "관망" and signal.ready_frames == 4
    assert signal.frames[tf].score == 50
    expected = 50 + sum(
        FRAME_WEIGHTS[k] * frame.coverage * (frame.score - 50)
        for k, frame in signal.frames.items()
        if frame.ready
    )
    assert signal.score.overall == pytest.approx(expected)


@pytest.mark.parametrize("tf", ("1h", "1w", "1M"))
def test_stale_horizon_cannot_confirm(tf):
    bundle = scenario()
    bundle[tf] = bundle[tf].iloc[:-2]
    signal = composite_signal(bundle, AS_OF)
    assert signal.frames[tf].stale
    assert not signal.frames[tf].ready
    assert signal.action == "관망"


@pytest.mark.parametrize("factory", (scenario, pullback_scenario))
def test_future_and_unfinished_candles_cannot_change_decision(factory):
    bundle = factory()
    before = composite_signal(bundle, AS_OF)
    altered = {}
    for tf, raw in bundle.items():
        future = raw.tail(1).copy() * 100
        future.index = pd.DatetimeIndex([candle_close(raw.index[-1], tf)], name="timestamp")
        altered[tf] = pd.concat([raw, future])
    assert composite_signal(altered, AS_OF) == before


def test_low_volume_vetoes_and_warmup_never_serializes_nan():
    bundle = scenario()
    bundle["1h"].iloc[-1, 4] = 1
    assert composite_signal(bundle, AS_OF).action == "관망"
    tiny = {tf: raw.tail(2) for tf, raw in bundle.items()}
    signal = composite_signal(tiny, AS_OF)
    assert signal.ready_frames == 0 and signal.score.overall == 50
    json.loads(dumps(signal))


def test_score_weight_order_does_not_change_decision():
    original = AppConfig()
    reordered = replace(
        original,
        strategy=replace(original.strategy, weights=dict(reversed(list(original.strategy.weights.items())))),
    )
    first = composite_signal(scenario(), AS_OF, original)
    second = composite_signal(scenario(), AS_OF, reordered)
    assert second.action == first.action
    assert second.score.overall == pytest.approx(first.score.overall)


def test_composite_signal_storage_is_distinct_and_idempotent(tmp_path):
    signal = composite_signal(pullback_scenario(), AS_OF)
    db = Database(tmp_path / "composite.sqlite")
    for _ in range(2):
        db.record_signal(signal, "Binance", "BTC/USDT", "ALL", "demo", "composite-v3-position:test")
    history = db.history("signals")
    assert len(history) == 1 and history.timeframe.iloc[0] == "ALL"
    assert json.loads(history.payload.iloc[0])["action"] == "매수"


def test_calendar_month_validation_in_leap_year_and_week_alignment():
    rows = [
        [pd.Timestamp(t), 10, 12, 9, 11, 100]
        for t in ("2024-01-01T00:00Z", "2024-02-01T00:00Z", "2024-03-01T00:00Z", "2024-03-02T00:00Z")
    ]
    february = normalize(rows, "1M", now="2024-02-29T23:59Z", timestamp_unit=None)
    assert len(february) == 1
    march = normalize(rows, "1M", now="2024-03-01T00:00Z", timestamp_unit=None)
    assert len(march) == 2 and march.attrs["quality"]["missing_candles"] == 0
    weekly = normalize(
        [
            [pd.Timestamp(t), 10, 12, 9, 11, 100]
            for t in ("2024-01-01T00:00Z", "2024-01-04T00:00Z", "2024-01-08T00:00Z")
        ],
        "1w",
        now="2024-01-15T00:00Z",
        timestamp_unit=None,
    )
    assert len(weekly) == 2 and weekly.attrs["quality"]["invalid_rows"] == 1


def test_monthly_gaps_restart_indicators_and_close_join_has_no_lookahead():
    bundle = scenario()
    next_week = bundle["1w"].tail(1).copy()
    next_week.index = pd.DatetimeIndex([candle_close(next_week.index[-1], "1w")], name="timestamp")
    bundle["1w"] = pd.concat([bundle["1w"], next_week])
    prepared = prepare({"1w": bundle["1w"], "1M": bundle["1M"]}, "1w")
    before_october = prepared.loc[prepared.available_at < pd.Timestamp("2026-10-01T00:00Z")].iloc[-1]
    assert before_october.close_1M == bundle["1M"].loc[pd.Timestamp("2026-08-01T00:00Z"), "close"]
    after_october = prepared.loc[prepared.available_at >= pd.Timestamp("2026-10-01T00:00Z")]
    assert not after_october.empty
    assert after_october.iloc[0].close_1M == bundle["1M"].close.iloc[-1]
    gap = bundle["1M"].drop(bundle["1M"].index[-3])
    signal = composite_signal({**bundle, "1M": gap}, AS_OF)
    assert signal.frames["1M"].bars == 2
    assert not signal.frames["1M"].ready and signal.action == "관망"


def test_monthly_confirmation_expires_at_next_calendar_close():
    index = pd.date_range("2024-01-01", periods=2, freq="MS", tz="UTC", name="timestamp")
    months = pd.DataFrame(
        {"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0}, index=index
    )
    # February is missing: January became available Feb 1 and expired Mar 1,
    # even though only 29 days elapsed in this leap year.
    weeks = scenario()["1w"].tail(1).copy()
    weeks.index = pd.DatetimeIndex([pd.Timestamp("2024-02-26T00:00Z")], name="timestamp")
    prepared = prepare({"1w": weeks, "1M": months.iloc[:1]}, "1w")
    assert pd.isna(prepared.close_1M.iloc[-1])


def test_macro_collection_keeps_successful_frames_on_failure(tmp_path, monkeypatch):
    calls = []
    sample = scenario()

    def fetch(self, exchange, symbol, tf, start, end, **kwargs):
        calls.append((tf, start))
        if tf == "1M":
            raise DataError("Monthly feed unavailable")
        return sample.get(tf, sample["1h"])

    monkeypatch.setattr(DataService, "fetch", fetch)
    bundle = DataService(tmp_path / "market.sqlite").bundle(
        "Binance", "BTC/USDT", "1h", AS_OF - pd.Timedelta(days=7), AS_OF, include_macro=True
    )
    assert bundle["1M"].empty and "unavailable" in bundle["1M"].attrs["error"]
    assert not bundle["1h"].empty
    assert next(start for tf, start in calls if tf == "1M") == pd.Timestamp("2017-08-01T00:00Z")
    assert composite_signal(bundle, AS_OF).action == "관망"


def test_macro_demo_is_shared_path_closed_and_realistic_monthly_history():
    bundle = demo_bundle("1h", 400, include_macro=True)
    assert set(COMPOSITE_TIMEFRAMES).issubset(bundle)
    assert 90 <= len(bundle["1M"]) < 200
    monthly = bundle["1M"]
    hourly = bundle["1h"]
    last_month = monthly.index[-1]
    hour_window = hourly.loc[(hourly.index >= last_month) & (hourly.index < candle_close(last_month, "1M"))]
    assert monthly.close.iloc[-1] == hour_window.close.iloc[-1]
    assert candle_close(monthly.index[-1], "1M") <= pd.Timestamp("2026-01-01T00:00Z")
