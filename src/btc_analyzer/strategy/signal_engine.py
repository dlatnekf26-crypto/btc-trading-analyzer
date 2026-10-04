"""Analysis snapshots and a stateful reset-aware signal gate."""

from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd
from btc_analyzer.analysis.support_resistance import zones, Zone
from btc_analyzer.config import AppConfig
from btc_analyzer.strategy.entry_engine import TradePlan, entry_plan
from btc_analyzer.strategy.scoring import Score, scoring, quality_label


@dataclass(frozen=True)
class Analysis:
    timestamp: str
    score: Score
    quality: float
    quality_label: str
    confidence: str
    regime: str
    volatility: str
    direction: str
    eligible: bool
    plan: TradePlan | None
    zones: list[Zone]
    reasons: list[str]
    narrative: str
    risk_multiplier: float

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(history: pd.DataFrame, cfg: AppConfig | None = None) -> Analysis:
    """Analyze the last CLOSED candle. Low-quality/missing-history setups stay No Trade."""
    cfg = cfg or AppConfig()
    row = history.iloc[-1]
    score = scoring(row, cfg.strategy)
    direction = "long" if score.overall >= 50 else "short"
    levels = zones(history, lookback=cfg.indicators.structure_window)
    plan = entry_plan(row, levels, direction, cfg.strategy)
    reasons = list(score.risks)
    conviction = abs(score.overall - 50) * 2
    # Quality rewards independent confluence as well as directional conviction.
    sign = 1 if direction == "long" else -1
    higher = float(row.get("higher_trend", 0))
    confluence = 8 * (sign * row.ema_alignment > 0.5) + 6 * (sign * higher > 0.3)
    confluence += 3 * (row.volume_ratio >= 1)
    confluence += 3 * (row.structure == ("Bullish Structure" if sign == 1 else "Bearish Structure"))
    quality = 0.45 * conviction + 35 + confluence
    warm = int(row.bars_since_gap) >= cfg.strategy.warmup_bars and np.isfinite(row.ema_200)
    if not warm:
        reasons.append("현재 연속 데이터의 워밍업 봉이 부족합니다.")
        quality = 0
    higher = float(row.get("higher_trend", 0))
    sign = 1 if direction == "long" else -1
    if sign * higher < -0.25:
        quality -= 30
        reasons.append("상위 추세와 진입 방향이 충돌합니다.")
    if float(row.get("higher_coverage", 0)) < 1:
        quality -= 20
    if row.volatility_regime == "Extreme Volatility":
        quality = min(quality, 40)
    if plan:
        if plan.effective_rr < cfg.strategy.min_rr:
            quality -= 35
            reasons.append("목표 분할청산의 평균 RR이 최소 기준보다 낮습니다.")
        if plan.rr[0] < 0.8:
            quality -= 15
            reasons.append("가까운 반대 영역으로 첫 목표의 RR이 낮습니다.")
        distance = abs(float(row.close) - plan.entry) / float(row.atr)
        if distance > 1.5:
            quality -= 25
            reasons.append("진입 영역에서 멀어 추격 진입을 피해야 합니다.")
        if abs(plan.entry - plan.stop) > float(row.atr) * 4:
            quality -= 20
            reasons.append("구조적 손절이 멀어 위험 대비 효율이 낮습니다.")
    else:
        quality = 0
        reasons.append("유효한 진입·손절·목표를 계산할 수 없습니다.")
    quality = float(np.clip(quality, 0, 100))
    directional_score = score.overall if direction == "long" else 100 - score.overall
    disabled = row.regime in cfg.strategy.disabled_regimes
    if disabled:
        reasons.append("설정에서 이 Regime의 신규 진입을 중지했습니다.")
    eligible = bool(
        warm
        and plan
        and quality >= cfg.strategy.min_quality
        and directional_score >= cfg.strategy.min_score
        and not disabled
        and plan.effective_rr >= cfg.strategy.min_rr
        and (direction == "long" or cfg.strategy.allow_short)
    )
    confidence = "High" if quality >= 85 else "Medium" if quality >= 65 else "Low"
    text = (
        f"현재 시장은 {row.regime}, 변동성은 {row.volatility_regime}입니다. "
        f"종합 점수 {score.overall:.1f}/100, 설정 품질 {quality:.1f}/100입니다. "
        + " ".join(score.positive + reasons)
        + (
            " 닫힌 봉 기준 후보이며 다음 봉 시가가 진입 영역에 들어올 때만 평가합니다."
            if eligible
            else " 신규 거래를 강제로 생성하지 않고 No Trade로 관찰합니다."
        )
    )
    return Analysis(
        str(history.index[-1]),
        score,
        quality,
        quality_label(quality),
        confidence,
        str(row.regime),
        str(row.volatility_regime),
        direction,
        eligible,
        plan,
        levels,
        reasons,
        text,
        cfg.strategy.regime_risk.get(row.regime, 1.0),
    )


@dataclass
class CooldownGate:
    """Require elapsed cooldown AND a condition/market reset before repeating an entry."""

    cooldown_bars: int
    last_bar: int = -1_000_000
    signature: str = ""
    reset_seen: bool = True

    def permit(self, bar: int, valid: bool, signature: str) -> bool:
        """Update reset state on every bar, including bars without an actionable signal."""
        if not valid or signature != self.signature:
            self.reset_seen = True
        return valid and self.reset_seen and bar - self.last_bar > self.cooldown_bars

    def fired(self, bar: int, signature: str) -> None:
        """Mark a generated candidate even if the next-open entry later expires."""
        self.last_bar, self.signature, self.reset_seen = bar, signature, False
