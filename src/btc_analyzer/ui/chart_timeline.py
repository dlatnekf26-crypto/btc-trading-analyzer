"""Equally spaced real candles; retain source dates for labels and live updates."""

import numpy as np
import pandas as pd

from btc_analyzer.config import TIMEFRAMES


def compact_timeline(spec, candle_times, timeframe, window):
    candles = np.asarray(candle_times, dtype=np.float64)
    # Keep displaced Ichimoku dates beyond the real candle window as well.
    outside = {
        x
        for trace in spec["data"]
        for x in trace["x"]
        if x is not None and (x < candles[0] or x > candles[-1])
    }
    source = np.asarray(sorted(outside | set(candles)), dtype=np.float64)
    step = TIMEFRAMES[timeframe] * 1000
    origin = float(candles[0])
    coordinates = origin + np.arange(len(source)) * step
    for trace in spec["data"]:
        source_x = np.asarray([np.nan if x is None else x for x in trace["x"]], dtype=np.float64)
        trace["x"] = [None if np.isnan(x) else float(x) for x in np.interp(source_x, source, coordinates)]
    positions = np.interp(candles, source, coordinates)
    start, end = positions[-window] - step * 0.7, positions[-1] + step * 1.5
    every = max(1, int(np.ceil(window / 5)))
    indices = range(len(candles) - window, len(candles), every)
    tickvals, ticktext = [], []
    for i in indices:
        tickvals.append(float(positions[i]))
        ticktext.append(
            pd.Timestamp(candles[i], unit="ms").strftime(
                "%m.%d<br>%H:%M" if timeframe in ("5m", "15m", "1h", "4h") else "%y.%m.%d"
            )
        )
    for name, axis in spec["layout"].items():
        if name.startswith("xaxis"):
            axis.update(
                range=[float(start), float(end)], tickmode="array", tickvals=tickvals, ticktext=ticktext
            )
    spec["layout"]["meta"]["btcLive"]["timeline"] = {
        "source": source.tolist(),
        "origin": origin,
        "step": step,
        "last": float(positions[-1]),
    }
    return spec
