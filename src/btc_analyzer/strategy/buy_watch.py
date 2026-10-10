"""Closed-candle, conditional watch prices; never an executable buy signal."""

from dataclasses import dataclass
import math

import pandas as pd

from btc_analyzer.config import AppConfig
from btc_analyzer.strategy.position_view import PositionView


@dataclass(frozen=True)
class BuyWatch:
    low: float | None = None
    high: float | None = None
    invalidation: float | None = None
    risk_floor: float | None = None
    target: float | None = None
    net_rr: float | None = None
    basis: str = ""
    reason: str = ""
    reference_price: float | None = None
    as_of: str | None = None
    valid_until: str | None = None


def watch_price(daily: pd.DataFrame | None, frames: dict, view: PositionView, cfg: AppConfig) -> BuyWatch:
    """Find a nearby observed pullback reference with a conservative net RR.

    The closest observed recovery reference must pay for risk at the *highest*
    entry. Clip only within an ATR band around actual support, never invent a
    distant cheap price or extrapolated target to make the RR pass.
    """
    if any(not frame.ready or frame.stale for frame in frames.values()):
        return BuyWatch(reason="다섯 시간대의 최신 확정 자료가 준비되면 가격대를 계산해요.")
    if view.falling_fast or view.broken_support:
        return BuyWatch(reason="급락 또는 지지 이탈 중이에요. 하락이 진정된 뒤 가격대를 다시 계산해요.")
    if any(frames[tf].volatility == "Extreme Volatility" for tf in ("4h", "1d", "1w")):
        return BuyWatch(reason="변동 위험이 커서 매수 검토 가격을 보류해요.")
    if frames["1w"].score < 48 or frames["1M"].score < 45 or view.macro_score < 50:
        return BuyWatch(reason="주봉·월봉 지지가 부족해요. 장기 흐름이 회복되면 가격대를 계산해요.")
    if any((frames[tf].indicators.get("volume_ratio") or 0) < 0.6 for tf in ("4h", "1d")):
        return BuyWatch(reason="일봉·4시간 거래량이 부족해요. 거래량이 회복되면 가격대를 다시 확인해요.")
    if daily is None or daily.empty or view.price is None or view.reference is None:
        return BuyWatch(reason="일봉 가격 근거가 충분하지 않아 가격대를 기다려요.")
    row = daily.iloc[-1]
    price, reference, atr = view.price, view.reference, float(row.atr)
    if not all(math.isfinite(n) and n > 0 for n in (price, reference, atr)):
        return BuyWatch(reason="유효한 일봉 가격·변동폭 자료가 필요해요.")
    recent = daily.tail(min(90, int(row.bars_since_gap)))

    def finite(n):
        return n is not None and pd.notna(n) and math.isfinite(float(n)) and float(n) > 0

    levels = [
        (row.get("last_swing_low"), "확정 일봉 스윙 저점"),
        (recent.low.iloc[:-1].tail(20).min(), "최근 20일 저점"),
        (row.get("ema_20"), "일봉 20일 이동평균"),
        (row.get("ema_50"), "일봉 50일 이동평균"),
        (row.get("ichimoku_kijun"), "일목 기준선"),
        (row.get("bb_lower"), "일봉 볼린저 하단"),
        *((n, "확정 일봉 스윙 저점") for n in recent.pivot_low.dropna()),
    ]
    anchors = sorted(
        {(float(n), label) for n, label in levels if finite(n) and float(n) <= price},
        reverse=True,
    )
    recoveries = sorted(
        {float(n) for n in [reference, row.get("last_swing_high"), *recent.pivot_high.dropna()] if finite(n)}
    )
    structural = [float(n) for n in (view.support, row.get("last_swing_low")) if finite(n)]
    width = cfg.strategy.entry_atr_width * atr
    buy_cost = (1 + cfg.risk.slippage) * (1 + cfg.risk.fee)
    sell_net = (1 - cfg.risk.slippage) * (1 - cfg.risk.fee)
    for anchor, label in anchors:
        # A discounted reference within six daily ATR / 25%; no remote limit.
        if reference - anchor < 0.5 * atr or price - anchor > min(6 * atr, price * 0.25):
            continue
        low = anchor - width
        stop = min([low, *[n for n in structural if n <= anchor]]) - cfg.strategy.atr_buffer * atr
        if stop <= 0 or low <= stop:
            continue
        # Include close resistance instead of skipping it to inflate rewards.
        target = next((n for n in recoveries if n > anchor), None)
        if target is None:
            continue
        ceiling = sell_net * (target + cfg.strategy.min_rr * stop) / (buy_cost * (1 + cfg.strategy.min_rr))
        high = min(anchor + width, ceiling)
        if high < anchor or low >= high:
            continue
        loss = high * buy_cost - stop * sell_net
        rr = (target * sell_net - high * buy_cost) / loss if loss > 0 else 0
        if rr + 1e-10 < cfg.strategy.min_rr:
            continue
        as_of = pd.Timestamp(frames["1h"].confirmed_at)
        risk_floors = [stop, float(row.close) * (1 - max(0.06, 2 * atr / price))]
        if len(recent) >= 4:
            risk_floors.append(float(recent.close.iloc[-4]) * (1 - max(0.08, 3 * atr / price)))
        return BuyWatch(
            low=low,
            high=high,
            invalidation=stop,
            risk_floor=max(risk_floors),
            target=target,
            net_rr=rr,
            basis=label,
            reason=f"{label} 주변의 일봉 변동폭과 중기 회복 기준을 비교했어요. 수수료·슬리피지 후 손익비 {rr:.2f}배를 충족해요.",
            reference_price=price,
            as_of=as_of.isoformat(),
            valid_until=(as_of + pd.Timedelta(hours=1)).isoformat(),
        )
    return BuyWatch(reason="가까운 지지·회복 목표로 비용 후 손익비를 충족하는 가격대가 아직 없어요.")
