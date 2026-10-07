"""Causal, unit-independent indicator families for analogue price estimates."""

from dataclasses import dataclass

import numpy as np

from btc_analyzer.indicators.core import indicators


# Each family gets one vote, regardless of its number of correlated indicators.
FAMILIES = (
    (
        "trend",
        "추세",
        (
            *[f"price_ema_{n}" for n in (9, 20, 50, 100, 200)],
            *[f"price_sma_{n}" for n in (20, 60, 120, 200)],
            "ema_slope",
            "adx",
        ),
        (*[0.05] * 9, 3.0, 25.0),
    ),
    (
        "momentum",
        "모멘텀",
        ("rsi", "rsi_slope", "macd", "macd_signal", "macd_hist", "macd_hist_slope"),
        (25.0, 15.0, 0.02, 0.02, 0.01, 0.01),
    ),
    (
        "volatility",
        "변동성",
        ("atr_pct", "bb_width", "bb_percent_b", "bb_width_change"),
        (3.0, 0.15, 0.5, 0.25),
    ),
    ("volume", "거래량", ("volume_ratio", "price_volume", "cmf"), (1.0, 2.0, 0.3)),
    (
        "ichimoku",
        "일목",
        (
            "price_tenkan",
            "price_kijun",
            "price_cloud_a",
            "price_cloud_b",
            "projected_cloud",
            "chikou_distance",
            "ichimoku_cloud_position",
            "ichimoku_tk_direction",
            "ichimoku_projected_direction",
            "ichimoku_chikou_direction",
        ),
        (0.05, 0.05, 0.05, 0.05, 0.05, 0.10, 1.0, 1.0, 1.0, 1.0),
    ),
)


@dataclass(frozen=True)
class IndicatorFamily:
    key: str
    label: str
    summary: str
    ready: int
    total: int
    similarity: float | None
    matched_cases: int


class TechnicalMatching:
    def __init__(self, frame, timeframe, context):
        self.features = features = indicators(frame, timeframe=timeframe)
        features["adx"], features["cmf"] = context[:, 1], context[:, 2]
        for prefix, periods in (("ema", (9, 20, 50, 100, 200)), ("sma", (20, 60, 120, 200))):
            for n in periods:
                features[f"price_{prefix}_{n}"] = features.close / features[f"{prefix}_{n}"] - 1
        for name in ("tenkan", "kijun", "cloud_a", "cloud_b"):
            features[f"price_{name}"] = features.close / features[f"ichimoku_{name}"] - 1
        features["projected_cloud"] = (features.ichimoku_span_a - features.ichimoku_span_b) / features.close
        features["chikou_distance"] = features.close / features.ichimoku_chikou_reference - 1
        self.arrays = []
        for _, _, keys, scales in FAMILIES:
            values = features[list(keys)].copy()
            # Compare relative MACD values across different absolute price levels.
            for key in keys:
                if key.startswith("macd"):
                    values[key] /= features.close
            self.arrays.append(values.to_numpy(dtype=float) / np.asarray(scales))
        self._cache = None

    def scores(self, last, window):
        if self._cache is not None and self._cache[0] == (last, window):
            return self._cache[1:]
        group_scores = np.full((last - window + 2, len(FAMILIES)), np.nan)
        active = 0
        for group, values in enumerate(self.arrays):
            known = np.isfinite(values[last])
            if not known.any():
                continue
            active += 1
            candidates = values[window - 1 : last + 1, known]
            finite = np.isfinite(candidates)
            count = finite.sum(axis=1)
            difference = np.where(finite, np.abs(candidates - values[last, known]), 0)
            distance = np.divide(difference.sum(axis=1), count, out=np.zeros(len(count)), where=count > 0)
            # Compare enough of the same known metrics; missing is never neutral.
            eligible = count >= max(1, int(np.ceil(known.sum() * 0.6)))
            group_scores[eligible, group] = 100 * np.exp(-distance[eligible])
        available = np.isfinite(group_scores).sum(axis=1)
        valid = (active >= 3) & (available == active)
        score = np.divide(
            np.nansum(group_scores, axis=1), available, out=np.zeros(len(available)), where=available > 0
        )
        score[~valid] = np.nan
        self._cache = ((last, window), score, group_scores)
        return score, group_scores

    def snapshot(self, last):
        return tuple(
            (key, float(value) if np.isfinite(value) else None)
            for key, value in self.features.iloc[last].items()
        )

    def describe(self, report, weights, last, window):
        _, scores = self.scores(last, window)
        indices = self.features.index.get_indexer([match.end for match in report.matches]) - window + 1
        row = self.features.iloc[last]
        summaries = (
            f"EMA 9·20·50·100·200 / SMA 20·60·120·200 · EMA20 대비 {_percent(row.price_ema_20)} · ADX {_plain(row.adx)}",
            f"RSI {_plain(row.rsi)} · RSI 변화 {_plain(row.rsi_slope)} · MACD {'상승 탄력' if row.macd_hist > 0 else '하락 탄력' if row.macd_hist < 0 else '중립' if np.isfinite(row.macd_hist) else '자료 부족'}",
            f"ATR {_plain(row.atr_pct)}% · 볼린저 폭 {_percent(row.bb_width)} · 밴드 내 위치 {_percent(row.bb_percent_b)}",
            f"평균 대비 거래량 {_plain(row.volume_ratio)}배 · CMF {_plain(row.cmf, 2)} · 거래량 동반 방향도 비교",
            f"구름 {'위' if row.ichimoku_cloud_position > 0 else '아래' if row.ichimoku_cloud_position < 0 else '안' if np.isfinite(row.ichimoku_cloud_position) else '자료 부족'} · 전환선/기준선·현재/선행 구름·후행 비교",
        )
        groups = []
        for group, ((key, label, keys, _), values, summary) in enumerate(
            zip(FAMILIES, self.arrays, summaries)
        ):
            similarities = scores[indices, group]
            mask = np.isfinite(similarities)
            similarity = (
                float(np.average(similarities[mask], weights=np.asarray(weights)[mask]))
                if mask.any()
                else None
            )
            groups.append(
                IndicatorFamily(
                    key,
                    label,
                    summary,
                    int(np.isfinite(values[last]).sum()),
                    len(keys),
                    similarity,
                    int(mask.sum()),
                )
            )
        return tuple(groups)


def _plain(value, digits=1):
    return f"{value:.{digits}f}" if np.isfinite(value) else "자료 부족"


def _percent(value):
    return f"{value:+.1%}" if np.isfinite(value) else "자료 부족"
