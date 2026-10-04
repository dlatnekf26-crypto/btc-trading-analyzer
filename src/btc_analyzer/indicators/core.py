"""Vectorized, causal technical indicators; Wilder averages use an explicit SMA seed."""

import numpy as np
import pandas as pd
from btc_analyzer.config import IndicatorConfig
from btc_analyzer.candles import candle_close


def ema(series: pd.Series, length: int) -> pd.Series:
    """Recursive EMA initialized with the first sample; hidden until length observations."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def wilder(series: pd.Series, length: int) -> pd.Series:
    """SMA-seeded Wilder smoothing (alpha = 1/length), not an EWM first-value seed."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    finite = np.flatnonzero(np.isfinite(values))
    if len(finite) < length:
        return pd.Series(out, index=series.index)
    start = finite[0]
    seed = start + length - 1
    if seed >= len(values) or not np.isfinite(values[start : seed + 1]).all():
        return pd.Series(out, index=series.index)
    out[seed] = values[start : seed + 1].mean()
    for i in range(seed + 1, len(values)):
        if np.isfinite(values[i]):
            out[i] = (out[i - 1] * (length - 1) + values[i]) / length
    return pd.Series(out, index=series.index)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI; flat series is neutral, only gains/losses yield 100/0."""
    delta = close.diff()
    gain, loss = wilder(delta.clip(lower=0), length), wilder(-delta.clip(upper=0), length)
    result = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    result = result.mask((loss == 0) & (gain > 0), 100)
    result = result.mask((gain == 0) & (loss > 0), 0)
    return result.mask((gain == 0) & (loss == 0), 50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal and histogram, with explicit EMA warmups."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Wilder ATR over high-low and previous-close gaps."""
    prev = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - prev).abs(), (df.low - prev).abs()], axis=1).max(axis=1)
    return wilder(tr, length)


def bollinger(close: pd.Series, length: int = 20, std: float = 2) -> pd.DataFrame:
    """Population standard deviation; squeeze threshold uses only prior widths."""
    middle = close.rolling(length, min_periods=length).mean()
    deviation = close.rolling(length, min_periods=length).std(ddof=0) * std
    upper, lower = middle + deviation, middle - deviation
    width = (upper - lower) / middle
    threshold = width.shift(1).rolling(100, min_periods=20).quantile(0.2)
    return pd.DataFrame(
        {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "bb_width": width,
            "bb_percent_b": (close - lower) / (upper - lower).replace(0, np.nan),
            "bb_squeeze": width < threshold,
            "bb_expansion": width > width.shift(1) * 1.1,
            "bb_width_change": width.pct_change(fill_method=None),
        }
    )


def _segment(df: pd.DataFrame, cfg: IndicatorConfig) -> pd.DataFrame:
    result = df.copy()
    for period in cfg.ema_lengths:
        result[f"ema_{period}"] = ema(df.close, period)
    for period in cfg.sma_lengths:
        result[f"sma_{period}"] = df.close.rolling(period, min_periods=period).mean()
    result["rsi"] = rsi(df.close, cfg.rsi_length)
    result = result.join(macd(df.close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal))
    result["atr"] = atr(df, cfg.atr_length)
    result["atr_pct"] = result.atr / result.close * 100
    result = result.join(bollinger(df.close, cfg.bb_length, cfg.bb_std))
    result["volume_sma"] = df.volume.rolling(cfg.volume_length).mean()
    result["volume_ratio"] = df.volume / result.volume_sma.replace(0, np.nan)
    result["price_change"] = df.close.pct_change(fill_method=None)
    result["price_volume"] = np.sign(result.price_change) * result.volume_ratio
    result["ema_slope"] = (
        result[f"ema_{cfg.fast_trend_length}"].pct_change(cfg.slope_length, fill_method=None) * 100
    )
    result["rsi_slope"] = result.rsi.diff(cfg.slope_length)
    result["macd_hist_slope"] = result.macd_hist.diff(cfg.slope_length)
    for prefix, periods in (("ema", cfg.ema_lengths), ("sma", cfg.sma_lengths)):
        pairs = [
            np.sign(result[f"{prefix}_{a}"] - result[f"{prefix}_{b}"])
            for a, b in zip(periods[:-1], periods[1:])
        ]
        result[f"{prefix}_alignment"] = sum(pairs) / len(pairs)
    result["price_vs_ema200"] = result.close / result.ema_200 - 1
    result["bars_since_gap"] = np.arange(1, len(result) + 1)
    return result


def indicators(
    df: pd.DataFrame, cfg: IndicatorConfig | None = None, timeframe: str | None = None
) -> pd.DataFrame:
    """Reset all recursive/rolling calculations at data gaps to avoid fictitious history."""
    cfg = cfg or IndicatorConfig()
    if df.empty:
        raise ValueError("No closed candles to analyze")
    tf = timeframe or df.attrs.get("timeframe", "1h")
    previous_close = candle_close(df.index.to_series().shift(), tf)
    groups = (df.index.to_series() != previous_close).cumsum()
    out = pd.concat([_segment(group, cfg) for _, group in df.groupby(groups)], axis=0)
    out.attrs = dict(df.attrs)
    return out
