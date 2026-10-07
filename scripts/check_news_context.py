"""Native macro/news and scenario controls with deterministic provider fixtures.

Run against a developer-injected Streamlit app; these checks cannot prove public
provider availability or improved forecast accuracy.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport


def verify(browser, width, url, event_log):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.get_by_role("tab", name="시장 개요", exact=True).wait_for(timeout=45000)
    page.locator("#macro-nq .btc-macro-value").get_by_text("22,345.50", exact=True).wait_for(timeout=15000)
    page.locator("#macro-tnx .btc-macro-value").get_by_text("4.25", exact=True).wait_for(timeout=15000)
    assert "수익률 지표" in page.locator("#macro-tnx").inner_text()
    page.locator("#macro-oil .btc-macro-value").get_by_text("87.42", exact=True).wait_for(timeout=15000)
    page.locator("#macro-tyx .btc-macro-value").get_by_text("4.80", exact=True).wait_for(timeout=15000)
    assert page.locator(".btc-macro-card svg").count() == 4
    page.locator(".btc-news-item:visible").first.wait_for(timeout=15000)
    assert page.locator(".btc-news-item:visible").count() == 3
    assert "Fixture News" in page.locator(".btc-news-item").first.inner_text()
    assert page.locator('iframe[src*="tradingview"]').count() == 0
    crypto = next(frame for frame in page.frames if frame.locator("#binance").count())
    sockets = crypto.evaluate("window.__quoteSockets.length")
    baseline = event_log.read_text() if event_log else None
    # Let the context fragment rerun; it must neither recalculate candles nor
    # recreate the iframe/socket containing live crypto quotes.
    page.wait_for_timeout(5500)
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    if baseline is not None:
        assert event_log.read_text() == baseline
    page.locator("#macro-nq").scroll_into_view_if_needed()
    page.screenshot(path=f"/tmp/btc-news-markets-{width}.png")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.get_by_role("tab", name="미래 예측", exact=True).click()
    page.get_by_role("radio", name="모델·과거 경로", exact=True).click()
    plot = page.get_by_role("tabpanel", name="미래 예측", exact=True).locator(".js-plotly-plot")
    plot.wait_for()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(e=>e.getBoundingClientRect().width>0 && e.data?.length===8)"
    )
    before = plot.evaluate("e=>e.data.map(t=>({name:t.name,x:t.x,y:t.y}))")
    assert before[-1]["name"] == "뉴스 반영 시나리오"
    assert page.locator(".btc-news-scenario").count() == 1
    baseline = event_log.read_text() if event_log else None
    page.get_by_text("2위", exact=True).click()
    page.wait_for_function(
        "b=>{const e=[...document.querySelectorAll('.js-plotly-plot')].find(e=>e.getBoundingClientRect().width>0 && e.data?.length===8);return e && JSON.stringify(e.data[4].y)!==b}",
        arg=json.dumps(before[4]["y"], separators=(",", ":")),
    )
    after = plot.evaluate("e=>e.data.map(t=>({name:t.name,x:t.x,y:t.y}))")
    assert before[:4] == after[:4] and before[5:] == after[5:]
    switch = page.get_by_text("뉴스 영향 함께 반영", exact=True)
    switch.click()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(e=>e.getBoundingClientRect().width>0 && e.data?.length===5)"
    )
    no_news = plot.evaluate("e=>e.data.map(t=>({name:t.name,x:t.x,y:t.y}))")
    assert before[:4] == no_news[:4]
    assert page.locator(".btc-news-scenario").count() == 0
    switch.click()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(e=>e.getBoundingClientRect().width>0 && e.data?.length===8)"
    )
    if baseline is not None:
        assert event_log.read_text() == baseline, "News controls recalculated parent analysis"
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    page.locator(".btc-forecast-cards").scroll_into_view_if_needed()
    page.screenshot(path=f"/tmp/btc-news-forecast-{width}.png")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not page.locator('[data-testid="stException"]').count()
    cleanup(page, page.main_frame)
    return {
        "width": width,
        "macro_quotes": "passed",
        "news": "passed",
        "scenario_controls": "passed",
        "independent_crypto": "passed",
        "parent_analysis_checked": baseline is not None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        print(json.dumps([verify(browser, width, args.app_url, args.event_log) for width in (1440, 390)]))
        browser.close()
