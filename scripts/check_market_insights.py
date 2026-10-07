"""Actual native heatmap touch/hover and fragment isolation with feed fixtures."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, send
from check_touch_charts import inspect, touch


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=width < 1000, is_mobile=width < 1000
    )
    page = context.new_page()
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    fear = page.locator('.btc-fear-card[data-score="32"]')
    fear.wait_for(timeout=45000)
    heatmap = page.locator(".btc-heatmap-card")
    heatmap.wait_for()
    page.wait_for_function("()=>document.querySelector('.js-plotly-plot')?.data?.length > 0")
    assert "일별 갱신" in fear.inner_text() and "Alternative.me" in fear.inner_text()
    assert page.locator(".btc-heatmap-cell").count() == 42
    assert page.locator(".js-plotly-plot:visible").count() == page.locator("iframe").count() == 1, (
        page.locator(".js-plotly-plot:visible").count(),
        page.locator("iframe").count(),
    )
    plot = page.locator(".js-plotly-plot:visible").first
    original = plot.evaluate("e=>JSON.stringify(e.data)")
    crypto = next(frame for frame in page.frames if frame.locator("#binance").count())
    crypto.locator('#binance[data-history="ready"]').wait_for()
    sockets = crypto.evaluate("window.__quoteSockets.length")
    baseline = event_log.read_text() if event_log else None
    label = page.locator(".btc-heatmap-cell label").nth(8)
    if width == 1440:
        assert page.evaluate("matchMedia('(hover:hover)').matches")
        page.mouse.move(0, 0)
        assert not label.locator(".btc-heatmap-detail").is_visible()
        label.hover()
        assert label.locator(".btc-heatmap-detail").is_visible()
        page.mouse.move(0, 0)
        assert not label.locator(".btc-heatmap-detail").is_visible()
    activate = "tap" if width < 1000 else "click"
    getattr(label, activate)()
    assert page.locator(".btc-heatmap-cell input:checked").count() == 1
    assert label.locator(".btc-heatmap-detail").is_visible()
    assert "완결 구간" in label.locator(".btc-heatmap-detail").inner_text()
    assert plot.evaluate("e=>JSON.stringify(e.data)") == original
    # Native cell selection and daily-index updates do not re-enter Python analysis.
    getattr(page.get_by_role("radio", name="최근 14일", exact=True), activate)()
    page.wait_for_function("()=>document.querySelector('.btc-heatmap-card')?.innerText.includes('최근 14일')")
    getattr(page.get_by_role("radio", name="최근 30일", exact=True), activate)()
    page.wait_for_function("()=>document.querySelector('.btc-heatmap-card')?.innerText.includes('최근 30일')")
    label = page.locator(".btc-heatmap-cell label").nth(8)
    getattr(label, activate)()
    heatmap.screenshot(path=f"/tmp/btc-insights-heatmap-{width}.png")
    fear.screenshot(path=f"/tmp/btc-insights-fear-{width}.png")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    label.scroll_into_view_if_needed()
    rect = label.bounding_box()
    cdp = context.new_cdp_session(page)
    if width == 1440:
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
    x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
    scroller = page.locator('[data-testid="stMain"]')
    before = scroller.evaluate("e=>e.scrollTop")
    touch(cdp, "touchStart", [(x, y)])
    for step in range(1, 6):
        touch(cdp, "touchMove", [(x, y - 100 * step / 5)])
        page.wait_for_timeout(30)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(200)
    assert scroller.evaluate("e=>e.scrollTop") > before + 20, "Heatmap trapped scrolling"
    inspect(page, cdp, plot, event_log, "market alongside native heatmap")
    send(crypto, "BTCUSDT", 100234, crypto.evaluate("Date.now()"))
    crypto.locator("#binance").wait_for()
    page.wait_for_timeout(200)
    assert "100,234" in crypto.locator("#binance").inner_text()
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    if baseline is not None:
        assert event_log.read_text() == baseline, "Insights re-entered candle/forecast analysis"
    assert not page.locator('[data-testid="stException"]').count()
    cleanup(page, page.main_frame)
    context.close()
    return {
        "width": width,
        "native_touch_hover": "passed",
        "two_periods": "passed",
        "daily_sentiment": "passed",
        "page_scroll_chart": "passed",
        "extra_iframes": 0,
        "parent_analysis_checked": baseline is not None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (390, 820, 1440):
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
