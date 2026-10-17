"""EMA/Bollinger values conditional on a displayed future closing-price path."""

import numpy as np

from btc_analyzer.market_clock import bar_closes, gap_groups

PROJECTION_FIELDS = ("ema_20", "ema_50", "ema_200", "bb_upper", "bb_middle", "bb_lower")


def projection_seed(frame, timeframe, cutoff):
    closed = frame.loc[bar_closes(frame, frame.index, timeframe) <= cutoff]
    if closed.empty:
        return None
    groups = gap_groups(closed, timeframe)
    close = closed.loc[groups == groups[-1], "close"]
    return {
        "count": len(close),
        "ema": {str(n): float(close.ewm(span=n, adjust=False).mean().iloc[-1]) for n in (20, 50, 200)},
        "tail": close.tail(20).tolist(),
    }


def project_indicators(seed, path):
    """path[0] is the existing anchor; never count that close a second time."""
    if not seed or len(path) == 0 or not np.isfinite(path).all() or min(path) <= 0:
        raise ValueError("예상 지표의 가격 경로가 유효하지 않습니다.")
    count, ema, tail = seed["count"], dict(seed["ema"]), list(seed["tail"])
    output = {name: [] for name in PROJECTION_FIELDS}
    for i, price in enumerate(path):
        if i:
            count += 1
            tail = [*tail[-19:], float(price)]
            for period in ema:
                alpha = 2 / (int(period) + 1)
                ema[period] += alpha * (price - ema[period])
        for period, value in ema.items():
            output["ema_" + period].append(value if count >= int(period) else None)
        mean = float(np.mean(tail)) if len(tail) == 20 else None
        width = float(np.std(tail, ddof=0) * 2) if mean is not None else None
        for name, value in (
            ("bb_middle", mean),
            ("bb_upper", None if mean is None else mean + width),
            ("bb_lower", None if mean is None else mean - width),
        ):
            output[name].append(value)
    return output
