"""Browser regression: ETH history recovery, bounded drawing and same-tab cache."""

import json

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, send, widget_html


def verify(browser, width):
    page = browser.new_page(viewport={"width": width, "height": 592}, device_scale_factor=1.1)
    page.clock.install()
    install_quote_transport(page)
    fixture = MarketFixture(page)
    fixture.history_failures["ethereum"] = 1
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("http://widget.test/", lambda r: r.fulfill(body=widget_html(), content_type="text/html"))
    page.goto("http://widget.test/")
    page.locator('#ethereum[data-history="retry"]').wait_for()
    page.locator("#ethereum .price span").get_by_text("3,000.25", exact=True).wait_for()
    now = page.evaluate("Date.now()")
    send(page, "ETHUSDT", 3100, now)
    page.clock.run_for(400)
    assert page.locator("#ethereum canvas").get_attribute("data-samples") == "1"
    with page.expect_response(lambda r: "klines?symbol=ETHUSDT" in r.url and r.status == 200):
        page.clock.run_for(23000)
    page.wait_for_timeout(100)
    page.clock.run_for(400)
    assert page.locator("#ethereum").get_attribute("data-history") == "ready"
    assert int(page.locator("#ethereum canvas").get_attribute("data-span")) >= 58 * 60000
    # History draws a full hour; a slower history response cannot overwrite a fresh quote.
    assert page.locator("#ethereum .price span").inner_text() in ("3,100.00", "3,000.25")
    canvas = page.locator("#ethereum canvas")
    canvas.evaluate(
        "el=>{window.__resizes=0;const prop=Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype,'height');Object.defineProperty(el,'height',{get(){return prop.get.call(this)},set(v){window.__resizes++;prop.set.call(this,v)}})}"
    )
    for price in (3101, 3102, 3103):
        send(page, "ETHUSDT", price, page.evaluate("Date.now()"))
        page.clock.run_for(400)
    assert page.evaluate("window.__resizes") == 0, "Fractional DPR reallocates Canvas on every tick"
    assert page.evaluate("document.querySelector('.note').getBoundingClientRect().bottom <= innerHeight")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    fixture.rest = False
    count = len([url for url, _ in fixture.requests if "klines?symbol=ETHUSDT" in url])
    page.reload()
    page.clock.run_for(400)
    assert page.locator("#ethereum").get_attribute("data-history") == "ready"
    assert int(page.locator("#ethereum canvas").get_attribute("data-span")) >= 58 * 60000
    assert page.locator("#ethereum.fresh").count() == 0
    assert count == len([url for url, _ in fixture.requests if "klines?symbol=ETHUSDT" in url])
    page.evaluate(
        "let c=JSON.parse(sessionStorage.getItem('btc-live-history-v2-ethereum'));c.at=Date.now()-61000;sessionStorage.setItem('btc-live-history-v2-ethereum',JSON.stringify(c));sessionStorage.setItem('btc-live-history-v2-binance','broken');sessionStorage.setItem('btc-reference-v1-fx',JSON.stringify({rate:1300,asOf:'bad',fetched:Date.now(),source:'은행 고시'}));"
    )
    page.reload()
    page.locator('#ethereum[data-history="retry"]').wait_for()
    assert page.locator("#ethereum canvas").get_attribute("data-samples") == "0"
    assert page.locator("#premium").get_attribute("data-ready") == "false"
    assert not errors, errors
    cleanup(page, page.main_frame)
    return {"width": width, "history_cache_fractional_dpr": "passed"}


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        print(json.dumps([verify(browser, width) for width in (1440, 390)]))
        browser.close()
