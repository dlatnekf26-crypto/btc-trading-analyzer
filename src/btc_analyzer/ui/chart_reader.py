"""Candle inspection stays in the browser; no requests or Python reruns."""

from btc_analyzer.ui.browser_assets import browser_asset

from html import escape
import math

from btc_analyzer.assets import MARKETS, price_text

FIELDS = {
    "rsi": "RSI 14",
    "macd": "MACD",
    "macd_signal": "시그널",
    "macd_hist": "MACD 차이",
    "open": "시가",
    "high": "고가",
    "low": "저가",
    "close": "종가",
    "ema_20": "EMA 20",
    "ema_50": "EMA 50",
    "ema_200": "EMA 200",
    "bb_upper": "볼린저 상단",
    "bb_middle": "볼린저 중심",
    "bb_lower": "볼린저 하단",
    "ichimoku_tenkan": "일목 전환선",
    "ichimoku_kijun": "일목 기준선",
}


def reader_html(frame, timeframe, asset_code, averages, bands):
    keys = ["open", "high", "low", "close", *averages]
    if bands:
        keys.extend(("bb_upper", "bb_middle", "bb_lower"))
    if "ichimoku_tenkan" in frame:
        keys.extend(("ichimoku_tenkan", "ichimoku_kijun"))
    keys.extend(key for key in ("rsi", "macd", "macd_signal", "macd_hist") if key in frame)
    row = frame.iloc[-1]

    def value(key):
        n = row.get(key)
        if n is None or not math.isfinite(n):
            return "—"
        if key.startswith("macd") and 0 < abs(n) < 0.0001:
            return f"{n:,.8f}"
        return price_text(n)

    cells = "".join(
        f'<div class="btc-read-{key}"><span>{FIELDS[key]}</span><b data-field="{key}">{value(key)}</b></div>'
        for key in keys
    )
    at = frame.index[-1].tz_convert("Asia/Seoul").strftime("%m.%d %H:%M")
    return (
        f'<section id="btc-chart-reader" class="btc-chart-reader" data-symbol="{MARKETS[asset_code].stream_symbol}" '
        f'data-timeframe="{escape(timeframe)}" data-decimals="{MARKETS[asset_code].decimals}" data-mode="latest" '
        'aria-label="가리킨 봉의 가격과 지표">'
        '<div class="btc-chart-toolbar"><div class="btc-cursor-reading">현재 가격 <b data-field="current">—</b><small> USDT</small><span class="btc-current-status" data-current-status>현재가 연결 중</span></div>'
        '<button type="button" class="btc-chart-auto" data-chart-action="auto" aria-pressed="true" title="현재 보이는 캔들에 가격축을 맞춰요">오토</button></div>'
        f'<div class="btc-reader-heading"><span data-reader-time>{at} KST · 마지막 확정 봉</span><span data-visible-bars></span></div>'
        f'<div class="btc-reader-values">{cells}</div>'
        "</section>"
    )


CHART_READER_JS = browser_asset("chart-viewport.js") + browser_asset("chart-reader.js")
