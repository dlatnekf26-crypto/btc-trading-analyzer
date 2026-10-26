"""Candle inspection stays in the browser; no requests or Python reruns."""

from html import escape
import math

from btc_analyzer.assets import MARKETS, SESSION_MARKETS, price_text
from btc_analyzer.indicators.averages import AVERAGE_COLORS

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
    "sma_20": "SMA 20",
    "sma_60": "SMA 60",
    "sma_120": "SMA 120",
    "bb_upper": "볼린저 상단",
    "bb_middle": "볼린저 중심",
    "bb_lower": "볼린저 하단",
    "ichimoku_tenkan": "일목 전환선",
    "ichimoku_kijun": "일목 기준선",
}

CHART_ACTIONS = (
    '<div class="btc-chart-actions"><button type="button" class="btc-chart-auto" data-chart-action="zoom" '
    'aria-pressed="false" title="켠 뒤 마우스로 좌우 드래그하면 봉 수를 조절해요. Shift+드래그나 휠도 사용할 수 있어요.">확대·축소</button>'
    '<button type="button" class="btc-chart-auto" data-chart-action="auto" aria-pressed="true" '
    'title="현재 보이는 캔들·경로에 가격축을 맞춰요">오토</button></div>'
)


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
        if key == "rsi":
            return f"{n:,.2f}"
        if key.startswith("macd") and 0 < abs(n) < 0.0001:
            return f"{n:,.8f}"
        return f"{n:,.0f}" if MARKETS[asset_code].decimals == 0 and key != "rsi" else price_text(n)

    cells = "".join(
        f'<div class="btc-read-{key}"><span>{FIELDS[key]}</span><b data-field="{key}">{value(key)}</b></div>'
        for key in keys
    )
    colors = {
        **AVERAGE_COLORS,
        "bb_middle": "#819bbd",
        "ichimoku_tenkan": "#3182f6",
        "ichimoku_kijun": "#dd9b24",
    }
    legend = "".join(
        f'<span><i style="--key-color:{colors[key]}"></i>{FIELDS[key]}</span>'
        for key in keys
        if key in colors
    )
    if "ichimoku_tenkan" in keys:
        legend += '<span><i class="btc-cloud-key"></i>일목 구름</span>'
    at = frame.index[-1].tz_convert("Asia/Seoul").strftime("%m.%d %H:%M")
    fallback = asset_code in SESSION_MARKETS and math.isfinite(row.get("close", float("nan")))
    fallback_status = f"{at} KST · 마지막 확정 봉 ({timeframe})"
    current = value("close") if fallback else "—"
    current_status = fallback_status if fallback else "현재가 연결 중"
    return (
        f'<section id="btc-chart-reader" class="btc-chart-reader" data-symbol="{MARKETS[asset_code].stream_symbol}" '
        f'data-timeframe="{escape(timeframe)}" data-decimals="{MARKETS[asset_code].decimals}" data-mode="latest" '
        f'data-fallback-status="{fallback_status if fallback else ""}" '
        'aria-label="가리킨 봉의 가격과 지표">'
        f'<div class="btc-chart-toolbar"><div class="btc-cursor-reading"><span data-current-label>{"마지막 가격" if fallback else "현재 가격"}</span> <b data-field="current">{current}</b><small> USDT</small><span class="btc-current-status" data-current-status>{current_status}</span></div>'
        f"{CHART_ACTIONS}</div>"
        f'<div class="btc-reader-heading"><span data-reader-time>{at} KST · 마지막 확정 봉</span><span data-visible-bars></span></div>'
        f'<div class="btc-reader-values">{cells}</div>'
        f'<div class="btc-chart-key" aria-label="차트 선 색상">{legend}</div>'
        "</section>"
    )
