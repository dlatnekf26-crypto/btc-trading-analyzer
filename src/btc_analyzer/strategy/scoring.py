"""Explainable directional scores, regime-adaptive weights and separate setup quality."""

from dataclasses import asdict, dataclass
import math
import numpy as np
import pandas as pd
from btc_analyzer.config import StrategyConfig


@dataclass(frozen=True)
class Score:
    overall: float
    label: str
    categories: dict[str, float]
    positive: list[str]
    risks: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def score_label(value: float) -> str:
    """Map continuous scores to the requested seven interpretation bands."""
    for threshold, label in [
        (85, "Very Strong Bullish"),
        (70, "Bullish"),
        (60, "Mild Bullish"),
        (40, "Neutral"),
        (30, "Mild Bearish"),
        (15, "Bearish"),
    ]:
        if value >= threshold:
            return label
    return "Very Strong Bearish"


def quality_label(value: float) -> str:
    """Quality is NOT a forecast probability or backtest-validated confidence."""
    for threshold, label in [
        (85, "High Quality Setup"),
        (75, "Valid Setup"),
        (65, "Weak Setup"),
        (50, "Watch"),
    ]:
        if value >= threshold:
            return label
    return "No Trade"


def _finite(row: pd.Series, name: str, fallback: float = 0) -> float:
    value = row.get(name, fallback)
    return float(value) if pd.notna(value) and math.isfinite(float(value)) else fallback


def scoring(row: pd.Series, cfg: StrategyConfig | None = None) -> Score:
    """Use contextual RSI/MACD evidence, never an isolated oversold/overbought rule."""
    cfg = cfg or StrategyConfig()
    alignment = _finite(row, "ema_alignment")
    slope = np.tanh(_finite(row, "ema_slope") / 0.25)
    price_trend = np.tanh(_finite(row, "price_vs_ema200") / 0.03)
    higher = _finite(row, "higher_trend")
    trend = 50 + 50 * (0.3 * alignment + 0.2 * slope + 0.2 * price_trend + 0.3 * higher)
    rsi = _finite(row, "rsi", 50)
    # RSI trend strength is directional; 75 in an uptrend contributes bullish momentum.
    momentum = 50 + 50 * (
        0.35 * np.clip((rsi - 50) / 30, -1, 1)
        + 0.2 * np.tanh(_finite(row, "rsi_slope") / 5)
        + 0.25 * np.tanh(_finite(row, "macd_hist") / max(_finite(row, "atr", 1) * 0.2, 1e-9))
        + 0.2 * np.tanh(_finite(row, "macd_hist_slope") / max(_finite(row, "atr", 1) * 0.1, 1e-9))
    )
    volume_ratio = _finite(row, "volume_ratio", 1)
    volume = 50 + 35 * np.sign(_finite(row, "price_change")) * min(max(volume_ratio - 0.5, 0), 1.5) / 1.5
    # Volatility has no intrinsic direction: it tempers directional conviction.
    directional = np.sign(trend - 50)
    penalty = {"Extreme Volatility": 0.2, "High Volatility": 0.5, "Low Volatility": 0.5}.get(
        row.volatility_regime, 1
    )
    volatility = 50 + 20 * directional * penalty
    structure = {
        "Bullish Structure": 85,
        "Bearish Structure": 15,
        "Range": 50,
        "Possible Transition": 50,
    }.get(row.structure, 50)
    support = _finite(row, "last_swing_low", float(row.close))
    resistance = _finite(row, "last_swing_high", float(row.close))
    if row.structure == "Bullish Structure" and 0 <= row.close - support <= _finite(row, "atr", 0) * 2:
        structure += 5
    if row.structure == "Bearish Structure" and 0 <= resistance - row.close <= _finite(row, "atr", 0) * 2:
        structure -= 5
    categories = {
        k: float(np.clip(v, 0, 100))
        for k, v in zip(
            ("trend", "momentum", "volume", "volatility", "structure"),
            (trend, momentum, volume, volatility, structure),
        )
    }
    weights = dict(cfg.weights)
    if row.regime == "Sideways":
        weights["trend"] *= 0.65
        # Mean reversion is weak contextual evidence only, gated by structure and higher trend.
        if abs(higher) < 0.35 and row.structure == "Range":
            categories["momentum"] = float(
                np.clip(
                    momentum * 0.6
                    + (50 + 20 * np.clip(0.5 - _finite(row, "bb_percent_b", 0.5), -1, 1)) * 0.4,
                    0,
                    100,
                )
            )
        weights["structure"] *= 1.4
        weights["volatility"] *= 1.4
    else:
        weights["trend"] *= 1.15
        weights["momentum"] *= 1.1
    total = sum(categories[k] * v for k, v in weights.items()) / sum(weights.values())
    total = 50 + (total - 50) * penalty if row.volatility_regime == "Extreme Volatility" else total
    positive, risks = [], []
    for condition, text in [
        (_finite(row, "price_vs_ema200") > 0, "가격이 EMA200 위에 있습니다."),
        (alignment >= 0.5, "단기·장기 EMA가 상승 배열입니다."),
        (higher > 0.3, "상위 타임프레임이 상승 추세를 확인합니다."),
        (_finite(row, "macd_hist_slope") > 0, "MACD 히스토그램이 개선 중입니다."),
        (
            volume_ratio >= 1.2 and _finite(row, "price_change") > 0,
            f"상승 봉 거래량이 평균의 {volume_ratio:.2f}배입니다.",
        ),
    ]:
        if condition:
            positive.append(text)
    for condition, text in [
        (higher < -0.3, "상위 타임프레임은 하락 우위입니다."),
        (_finite(row, "price_vs_ema200") < 0, "가격이 EMA200 아래에 있습니다."),
        (rsi > 70, "RSI 과열: 즉시 매도 규칙이 아닌 추격 진입 위험입니다."),
        (rsi < 30, "RSI 과매도: 단독 매수 근거로 사용하지 않습니다."),
        (row.volatility_regime in ("Extreme Volatility", "High Volatility"), "변동성이 높습니다."),
        (_finite(row, "higher_coverage", 1) < 1, "상위 봉 이력이 부족하거나 오래되었습니다."),
        (volume_ratio < 0.8, "거래량 확인이 약합니다."),
    ]:
        if condition:
            risks.append(text)
    return Score(float(np.clip(total, 0, 100)), score_label(total), categories, positive, risks)
