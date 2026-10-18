"""Small, local browser resources; compose once per checkout source generation."""

from functools import lru_cache
from pathlib import Path

BROWSER = Path(__file__).with_name("browser")


@lru_cache(maxsize=20)
def browser_asset(name):
    return (BROWSER / name).read_text(encoding="utf-8")


def live_analysis_js():
    return (
        browser_asset("plot-data.js")
        + browser_asset("candles.js")
        + browser_asset("project-indicators.js")
        + browser_asset("live-analysis.js")
    )


def quotes_document():
    code = browser_asset("quotes.js")
    for marker, value in (
        ("AI_FORECAST_BRIDGE", browser_asset("ai-forecast.js")),
        ("LIVE_ANALYSIS_BRIDGE", live_analysis_js()),
        (
            "CHART_READER_BRIDGE",
            browser_asset("chart-viewport.js")
            + browser_asset("chart-preview.js")
            + browser_asset("chart-reader.js"),
        ),
        ("PWA_BRIDGE", browser_asset("install.js")),
        ("RATES_BRIDGE", browser_asset("rates.js")),
        ("MACRO_BRIDGE", browser_asset("macro-quotes.js")),
        ("ALERTS_BRIDGE", browser_asset("move-alerts.js")),
    ):
        code = code.replace(f"/* {marker} */", value)
    return (
        browser_asset("quotes.html")
        .replace("/* QUOTES_CSS */", browser_asset("quotes.css"))
        .replace("/* QUOTES_JS */", code)
    )
