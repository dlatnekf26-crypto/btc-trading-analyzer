"""Exercise actual browser PricingData packets, freshness, fallback and lifecycle.

Public-provider fixtures prove behavior, not live feed availability or CME rights.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, send_macro, widget_html
from check_touch_charts import inspect, touch


SEED = """<div class="btc-macro-grid">
<article class="btc-macro-card" id="macro-nq" data-symbol="NQ=F" data-price="22345.5" data-asof="0" data-delay="15" data-points="22300,22345.5">
<div class="btc-macro-value">22,345.50</div><p class="btc-macro-change"></p><div class="btc-macro-graph"></div><p class="btc-macro-status"></p></article>
<article class="btc-macro-card" id="macro-oil" data-symbol="CL=F" data-price="87.42" data-asof="0" data-delay="10">
<div class="btc-macro-value">87.42</div><p class="btc-macro-change"></p><div class="btc-macro-graph"></div><p class="btc-macro-status"></p></article>
<article class="btc-macro-card" id="macro-tnx" data-symbol="^TNX" data-price="4.25" data-asof="0" data-delay="0" data-points="4.2,4.25">
<div class="btc-macro-value">4.25</div><p class="btc-macro-change"></p><div class="btc-macro-graph"></div><p class="btc-macro-status"></p></article>
<article class="btc-macro-card" id="macro-tyx" data-symbol="^TYX" data-price="4.80" data-asof="0" data-delay="0" data-points="4.7,4.8">
<div class="btc-macro-value">4.80</div><p class="btc-macro-change"></p><div class="btc-macro-graph"></div><p class="btc-macro-status"></p></article></div>"""


def verify(browser, width, url=None, event_log=None):
    page = browser.new_page(viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000)
    page.clock.install()
    install_quote_transport(page)
    MarketFixture(page)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if url:
        page.goto(url)
        page.get_by_role("tab", name="시장 개요", exact=True).wait_for(timeout=45000)
        page.locator("#macro-nq .btc-macro-value").get_by_text("22,345.50", exact=True).wait_for()
        widget = next(frame for frame in page.frames if frame.locator("#binance").count())
    else:
        page.route(
            "http://widget.test/",
            lambda route: route.fulfill(
                body=widget_html().replace('<div class="dashboard">', SEED + '<div class="dashboard">'),
                content_type="text/html",
            ),
        )
        page.goto("http://widget.test/")
        widget = page.main_frame
    widget.locator("#ethereum .price span").get_by_text("3,000.25", exact=True).wait_for()
    page.wait_for_timeout(100)
    assert (
        widget.evaluate(
            "window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com') && s.readyState===1).length"
        )
        == 1
    )
    assert widget.evaluate(
        "window.__subscriptions.some(s=>JSON.stringify(s.subscribe)===JSON.stringify(['NQ=F','CL=F','^TNX','^TYX','KRW=X']))"
    )
    baseline = event_log.read_text() if event_log else None
    now = page.evaluate("Date.now()")
    send_macro(widget, "NQ=F", 22600.5, now - 15 * 60000)
    send_macro(widget, "CL=F", 88.5, now - 10 * 60000)
    send_macro(widget, "^TNX", 4.5, now - 1000)
    send_macro(widget, "^TYX", 4.9, now - 1000)
    send_macro(widget, "KRW=X", 1348.5, now, currency="KRW")
    page.clock.run_for(50)
    for key, expected in (("nq", "22,600.50"), ("oil", "88.50"), ("tnx", "4.50"), ("tyx", "4.90")):
        assert page.locator(f"#macro-{key} .btc-macro-value").inner_text() == expected
    if not url:
        assert page.locator("#macro-oil .btc-macro-graph circle").count() == 1
    # React can keep the article while replacing or rewriting its children.
    page.locator("#macro-tyx .btc-macro-value").evaluate("e=>e.replaceWith(e.cloneNode(true))")
    page.locator("#macro-tyx .btc-macro-value").evaluate("e=>e.textContent='4.80'")
    page.locator("#macro-tnx .btc-macro-value").evaluate("e=>e.textContent='4.25'")
    page.clock.run_for(100)
    assert page.locator("#macro-tyx .btc-macro-value").inner_text() == "4.90"
    assert page.locator("#macro-tnx .btc-macro-value").inner_text() == "4.50"
    assert page.locator("#macro-oil .btc-macro-value").inner_text() == "88.50"
    assert page.locator("#macro-tyx .btc-macro-value").inner_text() == "4.90"
    assert "USD/배럴" in page.locator("#macro-oil .btc-macro-change").inner_text()
    assert "%p" in page.locator("#macro-tyx .btc-macro-change").inner_text()
    assert widget.locator("#forex .price span").inner_text() == "1,348.50"
    assert widget.locator("#forex").get_attribute("data-market") == "true"
    assert "Yahoo 시장" in widget.locator("#forex").inner_text()
    assert "15분" in page.locator("#macro-nq .btc-macro-status").inner_text()
    assert "실시간" not in page.locator("#macro-nq").inner_text()
    assert "10분" in page.locator("#macro-oil .btc-macro-status").inner_text()
    if url:
        # The two-second native fragment can replace a handle during Playwright's
        # stability wait. Resolve and scroll the current node synchronously.
        page.evaluate(
            "document.querySelector('.btc-macro-grid').scrollIntoView({block:'center',behavior:'instant'})"
        )
        assert page.locator(".btc-macro-card").count() == 4
        assert page.locator("iframe").count() == 1
        page.screenshot(path=f"/tmp/btc-macro-v2-cards-{width}.png")
        cdp = page.context.new_cdp_session(page)
        if width < 1000:
            box = page.locator("#macro-oil").bounding_box()
            x, y = box["x"] + box["width"] / 2, max(100, min(800, box["y"] + box["height"] / 2))
            scroller = page.locator('[data-testid="stMain"]')
            before = scroller.evaluate("e=>e.scrollTop")
            touch(cdp, "touchStart", [(x, y)])
            for step in range(1, 6):
                touch(cdp, "touchMove", [(x, y - step * 24)])
                page.wait_for_timeout(30)
            touch(cdp, "touchEnd")
            page.wait_for_timeout(200)
            assert scroller.evaluate("e=>e.scrollTop") > before + 20
        inspect(page, cdp, page.locator(".js-plotly-plot:visible").first, event_log, "four macro cards")
    for symbol, price, time, currency in (
        ("NQ=F", 1, now - 16 * 60000, "USD"),  # Out-of-order quote.
        ("^NDX", 1, now, "USD"),  # Cash index is not NQ futures.
        ("^TNX", 45, now, "USD"),  # Wrong yield scale.
        ("^TYX", 49, now, "USD"),
        ("BZ=F", 1, now, "USD"),  # Brent is not WTI.
        ("CL=F", 1, now, "KRW"),
        ("^TYX", 1, now + 60000, "USD"),
        ("KRW=X", 1, now, "USD"),  # Inverted/incorrect quote currency.
        ("KRW=X", 1, now + 60000, "KRW"),  # Future source timestamp.
        ("KRW=X", 1, now - 200000, "KRW"),  # Stale market FX.
        ("NQ=F", float("nan"), now, "USD"),
    ):
        send_macro(widget, symbol, price, time, currency=currency)
    for malformed in ('{"message":"AA=="}', '{"message":"@@@"}', "x" * 17000):
        widget.evaluate(
            "p=>window.__quoteSockets.find(s=>s.url.includes('streamer.finance.yahoo.com')).emit(p,false)",
            malformed,
        )
    page.clock.run_for(50)
    assert page.locator("#macro-nq .btc-macro-value").inner_text() == "22,600.50", {
        "value": page.locator("#macro-nq .btc-macro-value").inner_text(),
        "rest_asof": page.locator("#macro-nq").get_attribute("data-asof"),
        "stream_asof": now - 15 * 60000,
    }
    assert page.locator("#macro-tnx .btc-macro-value").inner_text() == "4.50"
    assert widget.locator("#forex .price span").inner_text() == "1,348.50"
    # Real Yahoo CCY packets may omit currency; unknown venues stay invalid.
    send_macro(widget, "KRW=X", 1349.5, now, currency=None, exchange="CCY")
    page.clock.run_for(50)
    assert widget.locator("#forex .price span").inner_text() == "1,349.50"
    send_macro(widget, "KRW=X", 1350.5, now, currency=None, exchange="UNKNOWN")
    page.clock.run_for(50)
    assert widget.locator("#forex .price span").inner_text() == "1,349.50"
    # A replaced native fragment and an older REST value cannot hide the stream.
    page.locator("#macro-nq").evaluate("e=>e.replaceWith(e.cloneNode(true))")
    page.locator("#macro-nq .btc-macro-value").evaluate("e=>e.textContent='22,345.50'")
    # Allow the parent MutationObserver delivery as well as the 50ms paint timer.
    page.clock.run_for(100)
    assert page.locator("#macro-nq .btc-macro-value").inner_text() == "22,600.50"
    # Freshness is shown on the next one-second watchdog paint.
    page.clock.run_for(16100)
    assert "수신 지연" in page.locator("#macro-nq .btc-macro-status").inner_text()
    if baseline is not None:
        assert event_log.read_text() == baseline, "Macro ticks reran parent analysis"
    before = widget.evaluate(
        "window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com')).length"
    )
    widget.evaluate(
        "window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com')).at(-1).close()"
    )
    page.clock.run_for(1200)
    assert (
        widget.evaluate(
            "window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com')).length"
        )
        == before + 1
    )
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
    )
    assert widget.evaluate("window.__quoteSockets.every(s=>s.readyState===3)")
    page.clock.run_for(5000)
    assert (
        widget.evaluate(
            "window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com')).length"
        )
        == before + 1
    )
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.clock.run_for(50)
    assert (
        widget.evaluate(
            "window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com') && s.readyState===1).length"
        )
        == 1
    )
    assert not errors, errors
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    cleanup(page, widget)
    return {
        "width": width,
        "mode": "embedded" if url else "standalone",
        "protocol": "passed",
        "freshness": "passed",
        "fallback": "passed",
        "reconnect_and_hidden": "passed",
        "tick_to_dom_bound_ms": 50,
        "parent_analysis_checked": baseline is not None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url")
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (1440, 390, 820) if args.app_url else (1440, 390):
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
