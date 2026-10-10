"""Watch prices remain conditional, causal and conservative after costs."""

from dataclasses import replace
import json

import pandas as pd
import numpy as np
import pytest

from btc_analyzer.config import AppConfig
from btc_analyzer.strategy.buy_watch import watch_price
from btc_analyzer.strategy.composite import composite_signal
from btc_analyzer.ui.presentation import decision_panel
from test_composite import AS_OF, scenario, pullback_scenario


def unsettled_bundle():
    bundle = pullback_scenario()
    for tf in ("1d", "4h"):
        frame = bundle[tf]
        close = frame.close.to_numpy().copy()
        close[-5:] = [102, 101.5, 100.9, 100.2, 99.44]
        opening = np.r_[close[0], close[:-1]]
        frame["close"], frame["open"] = close, opening
        frame["high"] = np.maximum(opening, close) + close * 0.004
        frame["low"] = np.minimum(opening, close) - close * 0.004
    return bundle


@pytest.fixture
def context():
    signal = composite_signal(scenario(), AS_OF)
    view = replace(
        signal.position,
        price=100,
        reference=110,
        support=90,
        macro_score=65,
        falling_fast=False,
        broken_support=False,
    )
    frames = {
        tf: replace(
            f,
            ready=True,
            stale=False,
            score=65,
            volatility="Normal Volatility",
            indicators={**f.indicators, "volume_ratio": 1.2},
        )
        for tf, f in signal.frames.items()
    }
    daily = pd.DataFrame(
        [
            dict(
                close=100,
                low=90,
                high=112,
                atr=4,
                bars_since_gap=90,
                last_swing_low=90,
                last_swing_high=112,
                pivot_high=112,
                pivot_low=90,
            )
        ],
        index=pd.date_range("2026-10-02", periods=2, tz="UTC"),
    )
    return daily, frames, view, AppConfig(), signal


def test_price_band_is_observed_support_not_a_fixed_discount(context):
    daily, frames, view, cfg, _ = context
    watch = watch_price(daily, frames, view, cfg)
    assert watch.low == 89 and watch.high == 91
    assert watch.invalidation == 87 and watch.target == 110
    assert watch.risk_floor == 92  # Two daily ATR is more than the six-percent floor.
    entry = watch.high * (1 + cfg.risk.slippage) * (1 + cfg.risk.fee)
    exit_net = (1 - cfg.risk.slippage) * (1 - cfg.risk.fee)
    assert watch.net_rr == pytest.approx(
        (watch.target * exit_net - entry) / (entry - watch.invalidation * exit_net)
    )
    assert watch.net_rr >= cfg.strategy.min_rr
    assert pd.Timestamp(watch.valid_until) - pd.Timestamp(watch.as_of) == pd.Timedelta(hours=1)
    changed = watch_price(daily, frames, replace(view, price=101), cfg)
    assert (changed.low, changed.high) == (watch.low, watch.high)
    original = daily.copy(deep=True)
    watch_price(daily, frames, view, cfg)
    pd.testing.assert_frame_equal(original, daily)


@pytest.mark.parametrize("change", ["crash", "broken", "macro", "extreme", "volume", "missing", "stale"])
def test_risk_or_missing_data_never_suggests_a_numeric_watch_price(context, change):
    daily, frames, view, cfg, _ = context
    if change == "crash":
        view = replace(view, falling_fast=True)
    if change == "broken":
        view = replace(view, broken_support=True)
    if change == "macro":
        frames["1w"] = replace(frames["1w"], score=40)
    if change == "extreme":
        frames["4h"] = replace(frames["4h"], volatility="Extreme Volatility")
    if change == "volume":
        frames["1d"] = replace(frames["1d"], indicators={"volume_ratio": 0.5})
    if change == "missing":
        frames["1M"] = replace(frames["1M"], ready=False)
    if change == "stale":
        frames["1h"] = replace(frames["1h"], stale=True)
    watch = watch_price(daily, frames, view, cfg)
    assert watch.low is watch.high is watch.target is None
    assert watch.reason


def test_costs_and_nearby_resistance_cannot_be_hidden_by_distant_targets(context):
    daily, frames, view, cfg, _ = context
    expensive = replace(cfg, risk=replace(cfg.risk, fee=0.08, slippage=0.02))
    assert watch_price(daily, frames, view, expensive).low is None
    daily["last_swing_high"] = 92
    assert watch_price(daily, frames, view, cfg).low is None
    assert watch_price(daily, frames, replace(view, price=130), cfg).low is None
    daily["atr"] = float("nan")
    assert watch_price(daily, frames, view, cfg).low is None


def test_net_rr_caps_upper_price_within_observed_support_band(context):
    daily, frames, view, cfg, _ = context
    required = replace(cfg, strategy=replace(cfg.strategy, min_rr=4.5))
    watch = watch_price(daily, frames, view, required)
    assert 90 <= watch.high < 91 and watch.low == 89
    assert watch.net_rr == pytest.approx(4.5)


def test_card_shows_conditional_price_reasons_without_changing_signal(context):
    daily, frames, view, cfg, signal = context
    watch = watch_price(daily, frames, view, cfg)
    signal = replace(signal, buy_watch=watch)
    html = decision_panel(signal)
    assert 'aria-label="조건부 매수 검토 가격대"' in html
    assert "89.00 ~ 91.00 USDT" in html and "수수료·슬리피지" in html
    assert "도달해도 하락 진정" in html and "자동 매수 신호가 아니에요" in html
    assert "10.04 21:00 KST" in html
    assert signal.action == "관망" and not signal.eligible and signal.plan is None
    assert "조건부 매수 검토 가격대" not in decision_panel(replace(signal, action="매수"))
    withheld = replace(signal, buy_watch=watch_price(daily, frames, replace(view, falling_fast=True), cfg))
    assert 'aria-label="매수 검토 가격 보류"' in decision_panel(withheld)
    assert "data-low=" not in decision_panel(withheld)
    json.dumps(signal.to_dict(), allow_nan=False)


def test_waiting_for_stabilization_gives_concrete_price_without_buying():
    signal = composite_signal(unsettled_bundle(), AS_OF)
    assert signal.action == "관망" and signal.plan is None and not signal.eligible
    assert signal.position.stability_score < 60
    assert 98 < signal.buy_watch.low < signal.buy_watch.high < signal.position.price
    assert signal.buy_watch.net_rr >= AppConfig().strategy.min_rr - 1e-10


@pytest.mark.parametrize("factory", [scenario, unsettled_bundle])
def test_active_signals_have_no_watch_and_hold_future_bars_cannot_change_watch(factory):
    assert composite_signal(pullback_scenario(), AS_OF).buy_watch is None
    assert composite_signal(scenario(-1), AS_OF).buy_watch is None
    bundle = factory()
    before = composite_signal(bundle, AS_OF)
    from btc_analyzer.candles import candle_close

    altered = {}
    for tf, raw in bundle.items():
        future = raw.tail(1).copy() * 100
        future.index = pd.DatetimeIndex([candle_close(raw.index[-1], tf)], name="timestamp")
        altered[tf] = pd.concat([raw, future])
    assert composite_signal(altered, AS_OF) == before
