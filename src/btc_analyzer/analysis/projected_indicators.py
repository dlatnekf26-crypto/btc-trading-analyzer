"""Market-specific averages/Bollinger values conditional on a future price path."""

import numpy as np

from btc_analyzer.market_clock import bar_closes, gap_groups
from btc_analyzer.indicators.averages import market_averages

BAND_FIELDS = ("bb_upper", "bb_middle", "bb_lower")


def projection_fields(seed):
    return (
        tuple("ema_" + n for n in seed["ema"]) + tuple(f"sma_{n}" for n in seed.get("sma", ())) + BAND_FIELDS
    )


def projection_seed(frame, timeframe, cutoff):
    closed = frame.loc[bar_closes(frame, frame.index, timeframe) <= cutoff]
    if closed.empty:
        return None
    groups = gap_groups(closed, timeframe)
    close = closed.loc[groups == groups[-1], "close"]
    averages = market_averages(frame.attrs.get("market"))
    ema_periods = [int(key.split("_")[1]) for key in averages if key.startswith("ema_")]
    sma_periods = [int(key.split("_")[1]) for key in averages if key.startswith("sma_")]
    return {
        "count": len(close),
        "ema": {str(n): float(close.ewm(span=n, adjust=False).mean().iloc[-1]) for n in ema_periods},
        "sma": sma_periods,
        "tail": close.tail(max([20, *sma_periods])).tolist(),
    }


def project_indicators(seed, path):
    """path[0] is the existing anchor; never count that close a second time."""
    if not seed or len(path) == 0 or not np.isfinite(path).all() or min(path) <= 0:
        raise ValueError("예상 지표의 가격 경로가 유효하지 않습니다.")
    count, ema, tail = seed["count"], dict(seed["ema"]), list(seed["tail"])
    sma = seed.get("sma", ())
    keep = max([20, *sma])
    output = {name: [] for name in projection_fields(seed)}
    for i, price in enumerate(path):
        if i:
            count += 1
            tail = [*tail[-(keep - 1) :], float(price)]
            for period in ema:
                alpha = 2 / (int(period) + 1)
                ema[period] += alpha * (price - ema[period])
        for period, value in ema.items():
            output["ema_" + period].append(value if count >= int(period) else None)
        for period in sma:
            output[f"sma_{period}"].append(float(np.mean(tail[-period:])) if len(tail) >= period else None)
        mean = float(np.mean(tail[-20:])) if len(tail) >= 20 else None
        width = float(np.std(tail[-20:], ddof=0) * 2) if mean is not None else None
        for name, value in (
            ("bb_middle", mean),
            ("bb_upper", None if mean is None else mean + width),
            ("bb_lower", None if mean is None else mean - width),
        ):
            output[name].append(value)
    return output
