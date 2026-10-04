"""Explainable five-horizon spot signals, using only available closed candles.

This is a separate snapshot rule set, not the single-timeframe paper/backtest
strategy. Missing indicators contribute neutral evidence, never invented EMA200.
"""

from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd

from btc_analyzer.analysis.multi_timeframe import enrich, prepare
from btc_analyzer.candles import candle_close
from btc_analyzer.config import AppConfig, COMPOSITE_TIMEFRAMES
from btc_analyzer.data.base_provider import utc
from btc_analyzer.strategy.scoring import Score, score_label
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.strategy.entry_engine import TradePlan

FRAME_WEIGHTS = {"1h": 0.15, "4h": 0.20, "1d": 0.30, "1w": 0.25, "1M": 0.10}
FRAME_LABELS = {"1h": "1시간", "4h": "4시간", "1d": "일봉", "1w": "주봉", "1M": "월봉"}


@dataclass(frozen=True)
class FrameSnapshot:
    timeframe: str
    confirmed_at: str | None
    bars: int
    ready: bool
    stale: bool
    score: float
    coverage: float
    categories: dict[str, float]
    indicators: dict[str, float | None]
    missing: list[str]
    notes: list[str]
    regime: str
    volatility: str


@dataclass(frozen=True)
class CompositeSignal:
    timestamp: str
    action: str
    direction: str
    score: Score
    quality: float
    regime: str
    eligible: bool
    agreement: int
    ready_frames: int
    reasons: list[str]
    frames: dict[str, FrameSnapshot]
    plan: TradePlan | None

    def to_dict(self) -> dict:
        return asdict(self)


def _number(row: pd.Series, key: str) -> float | None:
    value = row.get(key)
    return float(value) if value is not None and pd.notna(value) and math.isfinite(float(value)) else None


def _snapshot(raw: pd.DataFrame | None, tf: str, as_of: pd.Timestamp, cfg: AppConfig) -> FrameSnapshot:
    neutral = dict.fromkeys(cfg.strategy.weights, 50.0)
    if raw is None or raw.empty:
        note = (
            raw.attrs.get("error", "확정 봉 데이터가 없습니다.") if raw is not None else "데이터가 없습니다."
        )
        return FrameSnapshot(tf, None, 0, False, True, 50, 0, neutral, {}, [], [note], "Unknown", "Unknown")
    closed = raw.loc[candle_close(raw.index, tf) <= as_of]
    if closed.empty:
        return _snapshot(None, tf, as_of, cfg)
    frame = enrich(closed, tf, cfg)
    row = frame.iloc[-1]
    confirmed_at = candle_close(frame.index[-1], tf)
    stale = as_of >= candle_close(confirmed_at, tf)
    keys = [
        *(f"ema_{p}" for p in cfg.indicators.ema_lengths),
        *(f"sma_{p}" for p in cfg.indicators.sma_lengths),
        "rsi",
        "rsi_slope",
        "macd",
        "macd_signal",
        "macd_hist",
        "macd_hist_slope",
        "atr",
        "atr_pct",
        "bb_upper",
        "bb_middle",
        "bb_lower",
        "bb_width",
        "bb_percent_b",
        "volume_sma",
        "volume_ratio",
        "ema_slope",
    ]
    values = {key: _number(row, key) for key in keys}
    missing = [key for key, value in values.items() if value is None]
    coverage = 1 - len(missing) / len(keys)
    core = ("rsi", "macd_hist", "macd_hist_slope", "atr", "bb_middle", "volume_ratio", "ema_slope")
    ready = not stale and all(values[key] is not None for key in core) and float(row.atr) > 0
    notes = []
    if stale:
        notes.append("최신 확정 봉이 없어 이 시간대의 방향을 반영하지 않습니다.")
    if missing:
        notes.append("이력 부족 지표 제외: " + ", ".join(missing))
    if not ready and not stale:
        notes.append("핵심 지표 워밍업 또는 유효한 거래량이 부족합니다.")

    price = float(row.close)
    # All configured EMA/SMA locations, pair alignments and slope contribute.
    # Unknown long averages count as zero evidence in fixed denominators.
    locations, pairs = [], []
    for prefix, periods in (("ema", cfg.indicators.ema_lengths), ("sma", cfg.indicators.sma_lengths)):
        for period in periods:
            average = values[f"{prefix}_{period}"]
            locations.append(0 if average is None else np.tanh((price / average - 1) / 0.03))
        for a, b in zip(periods[:-1], periods[1:]):
            first, second = values[f"{prefix}_{a}"], values[f"{prefix}_{b}"]
            pairs.append(0 if first is None or second is None else np.sign(first - second))
    slope = np.tanh((values["ema_slope"] or 0) / 0.25)
    trend_evidence = 0.4 * np.mean(locations) + 0.4 * np.mean(pairs) + 0.2 * slope
    trend = 50 + 50 * trend_evidence
    atr_value = max(values["atr"] or 0, 1e-9)
    momentum = 50 + 50 * (
        0.35 * np.clip(((values["rsi"] if values["rsi"] is not None else 50) - 50) / 30, -1, 1)
        + 0.20 * np.tanh((values["rsi_slope"] or 0) / 5)
        + 0.25 * np.tanh((values["macd_hist"] or 0) / (atr_value * 0.2))
        + 0.20 * np.tanh((values["macd_hist_slope"] or 0) / (atr_value * 0.1))
    )
    ratio = values["volume_ratio"] if values["volume_ratio"] is not None else 1
    volume = 50 + 35 * np.sign(_number(row, "price_change") or 0) * np.clip(ratio - 0.5, 0, 1.5) / 1.5
    penalty = {"Extreme Volatility": 0.2, "High Volatility": 0.5, "Low Volatility": 0.5}.get(
        row.volatility_regime, 1
    )
    # Bollinger location confirms the trend; squeezing/expanding affects strength,
    # never an isolated overbought sell or oversold buy rule.
    band_direction = (
        0 if values["bb_percent_b"] is None else np.clip((values["bb_percent_b"] - 0.5) * 2, -1, 1)
    )
    band_strength = 0.5 if bool(row.bb_squeeze) else 1.0
    volatility = 50 + 20 * (0.7 * np.sign(trend_evidence) + 0.3 * band_direction) * penalty * band_strength
    structure = {"Bullish Structure": 85, "Bearish Structure": 15}.get(str(row.structure), 50)
    high, low = _number(row, "last_swing_high"), _number(row, "last_swing_low")
    if high is not None and price > high:
        structure = min(100, structure + 10)
    if low is not None and price < low:
        structure = max(0, structure - 10)
    # Configuration dict order must not alter category assignment.
    categories = dict(
        zip(
            ("trend", "momentum", "volume", "volatility", "structure"),
            (float(trend), float(momentum), float(volume), float(volatility), float(structure)),
        )
    )
    overall = sum(categories[k] * weight for k, weight in cfg.strategy.weights.items()) / sum(
        cfg.strategy.weights.values()
    )
    if row.volatility_regime == "Extreme Volatility":
        overall = 50 + (overall - 50) * penalty
    values.update(
        close=price,
        last_swing_high=high,
        last_swing_low=low,
        bb_squeeze=float(bool(row.bb_squeeze)),
        bb_expansion=float(bool(row.bb_expansion)),
        hh=float(bool(row.hh)),
        hl=float(bool(row.hl)),
        lh=float(bool(row.lh)),
        ll=float(bool(row.ll)),
    )
    return FrameSnapshot(
        tf,
        confirmed_at.isoformat(),
        int(row.bars_since_gap),
        ready,
        stale,
        float(overall),
        float(coverage),
        categories,
        values,
        missing,
        notes,
        str(row.regime),
        str(row.volatility_regime),
    )


def composite_signal(
    bundle: dict[str, pd.DataFrame], as_of: object, cfg: AppConfig | None = None
) -> CompositeSignal:
    """Missing/stale horizons and lower-vs-macro conflict veto buy/sell signals."""
    cfg = cfg or AppConfig()
    cutoff = utc(as_of)
    frames = {tf: _snapshot(bundle.get(tf), tf, cutoff, cfg) for tf in COMPOSITE_TIMEFRAMES}
    scores = {tf: (frame.score if frame.ready else 50.0) for tf, frame in frames.items()}
    total = 50 + sum(FRAME_WEIGHTS[tf] * frame.coverage * (scores[tf] - 50) for tf, frame in frames.items())
    categories = {
        key: 50
        + sum(
            FRAME_WEIGHTS[tf] * frame.coverage * (frame.categories[key] - 50)
            for tf, frame in frames.items()
            if frame.ready
        )
        for key in cfg.strategy.weights
    }
    bullish = sum(value >= 60 for value in scores.values())
    bearish = sum(value <= 40 for value in scores.values())
    ready_count = sum(frame.ready for frame in frames.values())
    reasons = [
        f"{FRAME_LABELS[tf]}: " + " ".join(frame.notes)
        for tf, frame in frames.items()
        if not frame.ready or frame.missing
    ]
    sign = 1 if total >= 50 else -1
    agreement = bullish if sign == 1 else bearish
    quality = sum(FRAME_WEIGHTS[tf] * frame.coverage for tf, frame in frames.items() if frame.ready) * 100
    action = "관망"
    plan = None
    buy_alignment = (
        scores["1h"] >= 60
        and scores["4h"] >= 60
        and scores["1d"] >= 60
        and scores["1w"] >= 50
        and scores["1M"] >= 45
    )
    sell_alignment = (
        scores["1h"] <= 40
        and scores["4h"] <= 40
        and scores["1d"] <= 40
        and scores["1w"] <= 50
        and scores["1M"] <= 55
    )
    volume_confirmed = all((frames[tf].indicators.get("volume_ratio") or 0) >= 0.8 for tf in ("1h", "4h"))
    extreme = any(frame.volatility == "Extreme Volatility" for frame in frames.values())
    if ready_count < 5:
        reasons.append("다섯 시간대의 핵심 지표와 최신 확정 봉이 갖춰질 때까지 관망합니다.")
    elif extreme:
        reasons.append("극단적 변동성이 있어 종합 매수·매도 신호를 보류합니다.")
    elif not volume_confirmed:
        reasons.append("1시간·4시간 거래량이 평균의 0.8배 미만이어서 신호를 보류합니다.")
    elif total >= cfg.strategy.min_score and buy_alignment:
        current = {
            tf: raw.loc[candle_close(raw.index, tf) <= cutoff]
            for tf, raw in bundle.items()
            if tf in ("1h", "4h", "1d")
        }
        entry = analyze(prepare(current, "1h", cfg), cfg)
        if entry.eligible and entry.direction == "long":
            action = "매수"
            plan = entry.plan
            reasons.append(
                "단기·일봉 상승과 장기 방향이 일치하고 1시간봉 진입 품질·손절·목표 RR 조건을 충족합니다."
            )
        else:
            reasons.append("상승 방향은 일치하지만 1시간봉 진입 품질·RR 조건이 부족하여 관망합니다.")
    elif total <= 100 - cfg.strategy.min_score and sell_alignment:
        action = "매도"
        reasons.append("단기·일봉 하락과 장기 방향이 일치합니다. 현물 보유분 축소를 검토하는 신호입니다.")
    else:
        reasons.append("시간대 방향이 충돌하거나 종합 점수가 기준에 미달하여 관망합니다.")
    for tf, frame in frames.items():
        if frame.ready:
            reasons.append(
                f"{FRAME_LABELS[tf]} 방향 점수 {frame.score:.1f}/100 · 반영 비중 {FRAME_WEIGHTS[tf]:.0%}"
            )
    direction = {"매수": "long", "매도": "sell", "관망": "hold"}[action]
    regime = "Uptrend" if total >= 60 else "Downtrend" if total <= 40 else "Sideways"
    score = Score(float(total), score_label(total), categories, [], reasons)
    timestamp = frames["1h"].confirmed_at or cutoff.isoformat()
    return CompositeSignal(
        timestamp,
        action,
        direction,
        score,
        float(quality),
        regime,
        action != "관망",
        agreement,
        ready_count,
        reasons,
        frames,
        plan,
    )
