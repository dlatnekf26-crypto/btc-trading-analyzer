"""Exercise browser quotes with real exchange message schemas, offline.

Requires Playwright and Chromium (development only); no extra app dependencies.
Use --app-url against an already running Live dashboard to also check embedding.
"""

import argparse
import ast
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright


def widget_html():
    path = Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/live_prices.py"
    module = ast.parse(path.read_text())
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LIVE_PRICES_HTML" for target in node.targets)
    )


def install_quote_transport(page):
    # Only replace the two public quote transports. Streamlit's own socket stays real.
    # Packet parsing, timers, drawing, DOM and the reconnect/fallback code remain production code.
    page.add_init_script(r"""
    (() => {
      const Native = window.WebSocket;
      window.__quoteSockets = []; window.__subscriptions = [];
      window.WebSocket = class {
        constructor(url) {
          if (!url.includes('data-stream.binance.vision') && !url.includes('api.upbit.com/websocket')) return new Native(url);
          this.url=url; this.readyState=0; window.__quoteSockets.push(this);
          setTimeout(()=>{this.readyState=1; this.onopen?.({});},0);
        }
        send(message) { window.__subscriptions.push(JSON.parse(message)); }
        close() { if(this.readyState===3) return; this.readyState=3; this.onclose?.({}); }
        emit(packet,binary) {
          if(this.readyState===1) this.onmessage?.({data:binary ? new TextEncoder().encode(packet).buffer : packet});
        }
        static CONNECTING=0; static OPEN=1; static CLOSING=2; static CLOSED=3;
      };
    })();
    """)


def verify(browser, width, app_url=None):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    page.clock.install()
    errors = []
    install_quote_transport(page)
    fixture = {"rest": True, "time": int(time.time() * 1000)}
    page.on("pageerror", lambda error: errors.append(str(error)))

    def quote(market, price=None, stamp=None):
        stamp = stamp or fixture["time"]
        if market == "binance":
            return {"s": "BTCUSDT", "c": str(price or 90000.25), "P": "2.34", "E": stamp}
        return {
            "code": "KRW-BTC",
            "trade_price": price or 130000000,
            "signed_change_rate": -0.0123,
            "timestamp": stamp,
        }

    def http_route(route):
        url = route.request.url
        market = "binance" if "binance" in url else "upbit"
        headers = {"Access-Control-Allow-Origin": "*"}
        if not fixture["rest"]:
            route.fulfill(status=503, body="Unavailable", headers=headers)
            return
        if "klines" in url or "candles" in url:
            end = fixture["time"] // 60000 * 60000
            rows = []
            for i in range(60):
                stamp = end - (59 - i) * 60000
                value = (90000 if market == "binance" else 130000000) + i * 3
                if market == "binance":
                    rows.append([stamp, value, value + 1, value - 1, str(value)])
                else:
                    from datetime import datetime, timezone

                    rows.append(
                        {
                            "candle_date_time_utc": datetime.fromtimestamp(
                                stamp / 1000, timezone.utc
                            ).strftime("%Y-%m-%dT%H:%M:%S"),
                            "trade_price": value,
                        }
                    )
            body = rows
        else:
            if market == "binance":
                body = {
                    "symbol": "BTCUSDT",
                    "lastPrice": "90000.25",
                    "priceChangePercent": "2.34",
                    "closeTime": fixture["time"],
                }
            else:
                body = quote(market)
                body["market"] = body.pop("code")
                body = [body]
        route.fulfill(json=body, headers=headers)

    page.route("https://data-api.binance.vision/**", http_route)
    page.route("https://api.upbit.com/**", http_route)
    if app_url:
        page.goto(app_url)
        page.locator("iframe").first.wait_for(timeout=45000)
        frame = page.locator("iframe").first.content_frame
        frame.locator("#binance .price span").get_by_text("90,000.25", exact=True).wait_for(timeout=15000)
        # Resolve the DOM frame for clock/data assertions.
        widget = next(f for f in page.frames if f != page.main_frame and f.locator("#binance").count())
        page.get_by_role("tab", name="시장 개요", exact=True).wait_for(timeout=45000)
        page.locator('[data-testid="stPlotlyChart"]').wait_for(timeout=45000)
    else:
        page.goto("about:blank")
        page.set_content(widget_html())
        widget = page.main_frame
        widget.locator("#binance .price span").get_by_text("90,000.25", exact=True).wait_for()

    def sockets(market):
        return widget.evaluate(
            "market=>window.__quoteSockets.filter(s=>s.url.includes(market)).length", market
        )

    def send(market, packet, binary=False):
        widget.evaluate(
            "([market,packet,binary])=>window.__quoteSockets.filter(s=>s.url.includes(market)).at(-1).emit(packet,binary)",
            [market, packet, binary],
        )

    assert sockets("binance") == sockets("upbit") == 1
    assert any(item[1]["codes"] == ["KRW-BTC"] for item in widget.evaluate("window.__subscriptions"))
    baseline = None
    event_file = Path("/tmp/btc-lean-browser-events.log")
    if app_url and event_file.exists():
        baseline = event_file.read_text()
    now = page.evaluate("Date.now()")
    for market, price in (("binance", 90123.45), ("upbit", 131000000)):
        data = json.dumps(quote(market, price, now))
        send(market, data, binary=market == "upbit")
    widget.locator("#binance .price span").get_by_text("90,123.45", exact=True).wait_for()
    page.wait_for_timeout(350)
    assert widget.locator("#upbit .price span").inner_text() == "131,000,000"
    assert "전일 대비 -1.23%" in widget.locator("#upbit .change").inner_text()
    assert "24시간 +2.34%" in widget.locator("#binance .change").inner_text()
    assert widget.locator(".fresh").count() == 2
    assert all(
        int(x) >= 59 for x in widget.locator("canvas").evaluate_all("els=>els.map(x=>x.dataset.samples)")
    )
    assert widget.locator("canvas").evaluate_all(
        "els=>els.every(x=>x.getContext('2d').getImageData(0,0,x.width,x.height).data.some(v=>v>0))"
    )

    # Invalid, out-of-order and cross-market quotes cannot alter either display.
    for data in (
        "not json",
        json.dumps(quote("binance", 1, now - 60000)),
        json.dumps({"s": "ETHUSDT", "c": "1", "E": now + 1}),
        json.dumps({"s": "BTCUSDT", "c": "-1", "E": now + 1}),
    ):
        send("binance", data)
    page.wait_for_timeout(300)
    assert widget.locator("#binance .price span").inner_text() == "90,123.45"
    if baseline is not None:
        assert event_file.read_text() == baseline, "Quote messages re-entered Python analysis"
    if app_url:
        widget.evaluate("window.__quoteProbe='preserve-this-connection'")
        page.get_by_role("tab", name="기술 지표", exact=True).click()
        page.get_by_text("모멘텀과 변동성", exact=True).wait_for()
        assert widget.evaluate("window.__quoteProbe") == "preserve-this-connection"
        assert widget.locator("#binance .price span").inner_text() == "90,123.45"
        page.get_by_role("tab", name="시장 개요", exact=True).click()
        page.get_by_text("차트로 확인하기", exact=True).wait_for()
    assert widget.evaluate(
        "document.getElementById('upbit').getBoundingClientRect().bottom <= innerHeight"
    ), "Live cards clipped by iframe"
    assert widget.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=f"/tmp/btc-lean-{width}.png", full_page=bool(app_url))

    # Freeze successful REST updates so old prices must become explicitly stale.
    fixture["rest"] = False
    page.clock.fast_forward(16000)
    page.clock.run_for(400)
    assert widget.locator(".stale").count() == 2
    assert "수신 지연" in widget.locator("#binance .status").inner_text()
    assert widget.locator("#binance .price span").inner_text() == "90,123.45"

    # A new message recovers the display, then a closed socket reconnects once.
    now = page.evaluate("Date.now()")
    send("binance", json.dumps(quote("binance", 90124, now)))
    page.clock.run_for(400)
    assert widget.locator("#binance.fresh").count() == 1
    count = sockets("binance")
    widget.evaluate("window.__quoteSockets.filter(s=>s.url.includes('binance')).at(-1).close()")
    page.clock.run_for(1700)
    assert sockets("binance") == count + 1

    # REST fallback uses a visibly different cadence, without claiming streaming.
    fixture.update(rest=True, time=page.evaluate("Date.now()") + 11000)
    with page.expect_response(
        lambda response: "/ticker/24hr" in response.url and response.status == 200
    ) as received:
        page.clock.fast_forward(11000)
    assert received.value.status == 200
    # Let the async fetch JSON microtask settle before advancing the mocked paint clock.
    page.wait_for_timeout(100)
    page.clock.run_for(700)
    assert "10초 조회" in widget.locator("#binance .status").inner_text(), {
        "status": widget.locator("#binance").inner_text(),
        "now": page.evaluate("Date.now()"),
        "fixture": fixture,
        "transport": widget.locator("#binance").get_attribute("data-transport"),
    }
    assert widget.locator("#binance .price span").inner_text() == "90,000.25"
    assert all(
        int(x) <= 61 for x in widget.locator("canvas").evaluate_all("els=>els.map(x=>x.dataset.samples)")
    )
    # A backgrounded page releases both sockets, then reconnects on return.
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    assert widget.evaluate("window.__quoteSockets.every(s=>s.readyState===3)")
    count = sockets("binance")
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:false}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.clock.run_for(400)
    assert sockets("binance") == count + 1
    assert not errors, errors
    result = {"width": width, "mode": "embedded" if app_url else "standalone", "passed": True}
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.wait_for_timeout(150)
    page.unroute_all(behavior="wait")
    page.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
        results = [verify(browser, width, args.app_url) for width in (1440, 390)]
        browser.close()
    print(json.dumps(results))


if __name__ == "__main__":
    main()
