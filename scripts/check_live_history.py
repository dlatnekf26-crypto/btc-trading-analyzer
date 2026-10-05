"""Browser regression: failed Upbit history recovers, preserves ticks and survives reload."""

import json
import time

from playwright.sync_api import sync_playwright

from check_live_widget import install_quote_transport, widget_html


def verify(browser, width):
    page = browser.new_page(viewport={"width": width, "height": 272})
    page.clock.install()
    install_quote_transport(page)
    errors, requests = [], []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    fixture = {"history_failures": 1, "blocked": False}
    page.route(
        "http://widget.test/", lambda route: route.fulfill(body=widget_html(), content_type="text/html")
    )

    def response(route):
        url = route.request.url
        market = "upbit" if "upbit" in url else "binance"
        history = "candles" in url or "klines" in url
        now = page.evaluate("Date.now()")
        requests.append((market, history, now))
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Retry-After": "11",
            "Access-Control-Expose-Headers": "Retry-After",
        }
        if fixture["blocked"] or (market == "upbit" and history and fixture["history_failures"]):
            if market == "upbit" and history:
                fixture["history_failures"] -= 1
            route.fulfill(status=429, body="Rate limit", headers=headers)
            return
        if history:
            price = 130000000 if market == "upbit" else 90000
            rows = []
            end = now // 60000 * 60000
            for i in range(60):
                stamp = end - (59 - i) * 60000
                rows.append(
                    {
                        "market": "KRW-BTC",
                        "candle_date_time_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(stamp / 1000)),
                        "trade_price": price + i,
                    }
                    if market == "upbit"
                    else [stamp, "0", "0", "0", str(price + i)]
                )
            body = rows
        elif market == "upbit":
            body = [
                {"market": "KRW-BTC", "trade_price": 131000000, "signed_change_rate": 0.01, "timestamp": now}
            ]
        else:
            body = {"symbol": "BTCUSDT", "lastPrice": "90000", "priceChangePercent": "1", "closeTime": now}
        route.fulfill(json=body, headers=headers)

    page.route("https://api.upbit.com/**", response)
    page.route("https://data-api.binance.vision/**", response)
    page.goto("http://widget.test/")
    page.locator('#upbit[data-history="retry"]').wait_for()
    now = page.evaluate("Date.now()")
    packet = json.dumps(
        {"code": "KRW-BTC", "trade_price": 131000000, "signed_change_rate": 0.01, "timestamp": now}
    )
    page.evaluate("packet=>window.__quoteSockets.find(s=>s.url.includes('upbit')).emit(packet,true)", packet)
    page.clock.run_for(400)
    assert page.locator("#upbit canvas").get_attribute("data-samples") == "1"
    assert [r[1] for r in requests if r[0] == "upbit"] == [True], "History must precede quote REST"
    page.clock.run_for(11500)
    page.wait_for_timeout(100)
    with page.expect_response(lambda r: "upbit.com/v1/candles" in r.url and r.status == 200):
        page.clock.run_for(11500)
    page.wait_for_timeout(100)
    page.clock.run_for(400)
    assert page.locator("#upbit").get_attribute("data-history") == "ready"
    assert int(page.locator("#upbit canvas").get_attribute("data-samples")) >= 59
    assert int(page.locator("#upbit canvas").get_attribute("data-span")) >= 58 * 60000
    assert page.locator("#upbit .price span").inner_text() == "131,000,000", "History overwrote a newer tick"
    upbit_requests = [r[2] for r in requests if r[0] == "upbit"]
    assert all(b - a >= 11000 for a, b in zip(upbit_requests, upbit_requests[1:])), upbit_requests
    assert page.evaluate("document.getElementById('upbit').getBoundingClientRect().bottom <= innerHeight"), (
        page.locator(".market").evaluate_all(
            "els=>els.map(x=>({height:x.offsetHeight,bottom:x.getBoundingClientRect().bottom}))"
        )
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # A same-tab reload starts with the saved full graph even if REST is unavailable.
    fixture["blocked"] = True
    history_requests = len([r for r in requests if r[0] == "upbit" and r[1]])
    page.reload()
    page.clock.run_for(400)
    assert page.locator("#upbit").get_attribute("data-history") == "ready"
    assert int(page.locator("#upbit canvas").get_attribute("data-span")) >= 58 * 60000
    assert page.locator("#upbit.fresh").count() == 0, "Cached history is not a live quote"
    assert history_requests == len([r for r in requests if r[0] == "upbit" and r[1]])
    # Expired history cannot masquerade as current; malformed storage cannot crash.
    page.evaluate(
        "let c=JSON.parse(sessionStorage.getItem('btc-live-history-v2-upbit')); c.at=Date.now()-61000; sessionStorage.setItem('btc-live-history-v2-upbit',JSON.stringify(c)); sessionStorage.setItem('btc-live-history-v2-binance','broken');"
    )
    page.reload()
    page.locator('#upbit[data-history="retry"]').wait_for()
    assert page.locator("#upbit canvas").get_attribute("data-samples") == "0"
    assert not errors, errors
    page.screenshot(path=f"/tmp/btc-refine-history-{width}.png")
    page.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.wait_for_timeout(150)
    page.unroute_all(behavior="wait")
    page.close()
    return {"width": width, "history_recovery_cache": "passed"}


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        print(json.dumps([verify(browser, width) for width in (1440, 390)]))
        browser.close()
