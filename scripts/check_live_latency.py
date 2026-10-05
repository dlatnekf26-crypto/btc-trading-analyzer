"""Measure production tick-to-DOM scheduling, trade parsing and macro isolation.

The browser clock is controlled: these timings exclude network/exchange delay.
Use --widget-file to measure an archived implementation with the same fixtures.
"""

import argparse
import ast
import json
from pathlib import Path
import statistics

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, widget_html


def html(path):
    if path is None:
        return widget_html()
    module = ast.parse(path.read_text())
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "LIVE_PRICES_HTML" for t in node.targets)
    )


def emit(page, data):
    page.evaluate(
        """data=>{
      const socket=window.__quoteSockets.filter(s=>s.url.includes('btcusdt@')).at(-1);
      socket.emit(JSON.stringify(socket.url.includes('/stream?') ? {stream:'btcusdt@ticker',data} : data),false);
    }""",
        data,
    )


def verify(browser, source, width, archived):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    page.clock.install()
    install_quote_transport(page)
    fixture = MarketFixture(page)
    page.route("http://widget.test/", lambda r: r.fulfill(body=source, content_type="text/html"))
    page.goto("http://widget.test/")
    page.wait_for_timeout(100)
    page.clock.run_for(1310)
    samples = []
    for i in range(9):
        price = 101000 + i
        emit(page, {"s": "BTCUSDT", "c": str(price), "P": "2.34", "E": page.evaluate("Date.now()")})
        delay = 0
        while page.locator("#binance .price span").inner_text() != f"{price:,.2f}":
            page.clock.run_for(10)
            delay += 10
            assert delay <= 300, "A valid tick was never rendered"
        samples.append(delay)
        page.clock.run_for(300)
    result = {"width": width, "tick_to_dom_median_ms": statistics.median(samples), "samples_ms": samples}
    if not archived:
        assert max(samples) <= 100
        # Trade packets arrive independently of the one-second ticker, and
        # retain the last valid 24-hour percentage rather than clearing it.
        emit(page, {"s": "BTCUSDT", "e": "aggTrade", "p": "102345.67", "E": page.evaluate("Date.now()")})
        page.clock.run_for(100)
        assert page.locator("#binance .price span").inner_text() == "102,345.67"
        assert "+2.34%" in page.locator("#binance .change").inner_text()
        assert page.evaluate("window.__quoteSockets.length") == 2
        urls = page.evaluate("window.__quoteSockets.map(s=>s.url)")
        assert sum("data-stream.binance.vision" in url for url in urls) == 1
        assert "ethusdt@aggTrade" in urls[0] and "btcusdt@aggTrade" in urls[0]
        page.evaluate(
            "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
        )
        page.wait_for_timeout(100)
        page.evaluate(
            "Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))"
        )
        assert page.locator("iframe").count() == 0
        emit(page, {"s": "BTCUSDT", "e": "aggTrade", "p": "102346.67", "E": page.evaluate("Date.now()")})
        page.clock.run_for(100)
        assert page.locator("#binance .price span").inner_text() == "102,346.67"
        calls = [t for url, t in fixture.requests if "/ticker/24hr?symbols=" in url]
        assert calls and all(b - a >= 5000 for a, b in zip(calls, calls[1:]))
        assert not any("/ticker/24hr?symbol=" in url for url, _ in fixture.requests)
        result.update(trade_packet="passed", external_embeds=0, binance_connections=1)
    cleanup(page, page.main_frame)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--widget-file", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        print(
            json.dumps(
                [
                    verify(browser, html(args.widget_file), w, args.widget_file is not None)
                    for w in (1440, 390)
                ]
            )
        )
        browser.close()
