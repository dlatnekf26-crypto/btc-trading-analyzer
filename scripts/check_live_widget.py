"""Exercise browser quotes with real exchange message schemas, offline.

Requires Playwright and Chromium (development only); no extra app dependencies.
Use --app-url against an already running Live dashboard to also check embedding.
"""

import argparse
import ast
import json
from pathlib import Path

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
    # Only replace the public quote transports. Streamlit's own socket stays real.
    # Packet parsing, timers, drawing, DOM and the reconnect/fallback code remain production code.
    page.add_init_script(r"""
    (() => {
      const Native = window.WebSocket;
      window.__quoteSockets = []; window.__subscriptions = [];
      const nativeFetch=window.fetch;
      window.__quoteFetches=[];
      window.fetch=(...args)=>{
        const url=typeof args[0]==='string' ? args[0] : args[0].url;
        if (url.startsWith('https://data-api.binance.vision/')) window.__quoteFetches.push({url,time:Date.now()});
        return nativeFetch(...args);
      };
      window.WebSocket = class {
        constructor(url) {
          if (!url.includes('data-stream.binance.vision') && !url.includes('api.upbit.com/websocket') && !url.includes('streamer.finance.yahoo.com')) return new Native(url);
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


class MarketFixture:
    """Official response shapes with controllable errors and source timestamps."""

    def __init__(self, page):
        self.page = page
        self.rest = True
        self.fx_fail = False
        self.fallback_fail = False
        self.peg_fail = False
        self.fx_age_days = 0
        self.peg_age_ms = 0
        self.peg_price = 1.02
        self.fx_price = 1300.0
        self.history_failures = {}
        self.requests = []
        for host in (
            "data-api.binance.vision",
            "api.upbit.com",
            "quotation-api-cdn.dunamu.com",
            "api.frankfurter.dev",
            "api.exchange.coinbase.com",
        ):
            page.route("https://" + host + "/**", self.route)

    def route(self, route):
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        from urllib.parse import parse_qs, urlparse

        url = route.request.url
        now = self.page.evaluate("Date.now()")
        stamp = datetime.fromtimestamp(now / 1000, timezone.utc)
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Retry-After": "11",
            "Access-Control-Expose-Headers": "Retry-After",
        }
        market = "ethereum" if "ETHUSDT" in url else "upbit" if "api.upbit.com" in url else "binance"
        history = "klines" in url
        self.requests.append((url, now))
        failure = not self.rest
        if history and self.history_failures.get(market, 0):
            self.history_failures[market] -= 1
            failure = True
        if "forex/recent" in url:
            kst = (stamp - timedelta(days=self.fx_age_days)).astimezone(ZoneInfo("Asia/Seoul"))
            failure |= self.fx_fail
            body = [
                {
                    "code": "FRX.KRWUSD",
                    "currencyCode": "USD",
                    "currencyUnit": 1,
                    "basePrice": self.fx_price,
                    "date": kst.strftime("%Y-%m-%d"),
                    "time": kst.strftime("%H:%M:%S"),
                }
            ]
        elif "frankfurter" in url:
            failure |= self.fallback_fail
            body = {
                "base": "USD",
                "amount": 1,
                "date": (stamp - timedelta(days=self.fx_age_days)).strftime("%Y-%m-%d"),
                "rates": {"KRW": self.fx_price},
            }
        elif "coinbase" in url:
            failure |= self.peg_fail
            body = {
                "price": str(self.peg_price),
                "time": (stamp - timedelta(milliseconds=self.peg_age_ms)).isoformat(),
            }
        elif history:
            end = now // 60000 * 60000
            base = 3000 if market == "ethereum" else 100000
            body = [[end - (59 - i) * 60000, base, base, base, str(base + i)] for i in range(60)]
        elif market == "upbit":
            body = [
                {"market": "KRW-BTC", "trade_price": 135252000, "signed_change_rate": 0.01, "timestamp": now}
            ]
        else:
            query = parse_qs(urlparse(url).query)
            symbols = json.loads(query["symbols"][0]) if "symbols" in query else query["symbol"]
            quotes = [
                {
                    "symbol": symbol,
                    "lastPrice": "3000.25" if symbol == "ETHUSDT" else "100000",
                    "priceChangePercent": "2.34",
                    "closeTime": now,
                }
                for symbol in symbols
            ]
            body = quotes if "symbols" in query else quotes[0]
        if failure:
            route.fulfill(status=429, body="Rate limited", headers=headers)
        else:
            route.fulfill(json=body, headers=headers)


def send(widget, symbol, price, now):
    import json

    token = "api.upbit.com" if symbol == "KRW-BTC" else symbol.lower() + "@"
    data = (
        {"code": symbol, "trade_price": price, "signed_change_rate": 0.01, "timestamp": now}
        if symbol == "KRW-BTC"
        else {"s": symbol, "c": str(price), "P": "2.34", "E": now}
    )
    if symbol != "KRW-BTC":
        data = {"stream": symbol.lower() + "@ticker", "data": data}
    widget.evaluate(
        "([token,packet,binary])=>window.__quoteSockets.filter(s=>s.url.includes(token)).at(-1).emit(packet,binary)",
        [token, json.dumps(data), symbol == "KRW-BTC"],
    )


def cleanup(page, widget):
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.wait_for_timeout(150)
    page.unroute_all(behavior="wait")
    page.close()


def send_macro(widget, symbol, price, now, *, currency="USD", change=1.25, exchange=None):
    """Encode the provider's independent PricingData schema, including sint64 time."""
    import base64
    import struct

    def varint(number):
        output = bytearray()
        while number >= 128:
            output.append((number & 127) | 128)
            number >>= 7
        output.append(number)
        return bytes(output)

    def string(field, value):
        encoded = value.encode()
        return varint(field * 8 + 2) + varint(len(encoded)) + encoded

    wire = (
        string(1, symbol)
        + bytes([2 * 8 + 5])
        + struct.pack("<f", price)
        + bytes([3 * 8])
        + varint(now * 2 if now >= 0 else -now * 2 - 1)
        + (string(4, currency) if currency is not None else b"")
        + (string(5, exchange) if exchange is not None else b"")
        + bytes([8 * 8 + 5])
        + struct.pack("<f", change)
    )
    packet = json.dumps({"message": base64.b64encode(wire).decode()})
    widget.evaluate(
        "p=>window.__quoteSockets.filter(s=>s.url.includes('streamer.finance.yahoo.com')).at(-1).emit(p,false)",
        packet,
    )


def verify(browser, width, app_url=None, event_log=None):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    page.clock.install()
    install_quote_transport(page)
    fixture = MarketFixture(page)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if app_url:
        page.goto(app_url)
        page.locator("iframe").first.wait_for(timeout=45000)
        widget = next(f for f in page.frames if f != page.main_frame and f.locator("#binance").count())
        page.get_by_role("tab", name="시장 개요", exact=True).wait_for(timeout=45000)
        page.locator('[data-testid="stPlotlyChart"]').wait_for(timeout=45000)
    else:
        page.route("http://widget.test/", lambda r: r.fulfill(body=widget_html(), content_type="text/html"))
        page.goto("http://widget.test/")
        widget = page.main_frame
    widget.locator('#premium[data-ready="true"]').wait_for(timeout=20000)
    assert widget.locator("#upbit").count() == 0
    assert widget.locator(".market").count() == 4
    assert widget.locator("iframe").count() == 0
    assert widget.evaluate("window.__quoteSockets.length") == 3
    assert widget.locator("#ethereum .price span").inner_text() == "3,000.25"
    fx = float(widget.locator("#forex .price span").inner_text().replace(",", ""))
    assert fx in (1300.0, 1345.5)
    assert (
        abs(
            float(widget.locator("#premium").get_attribute("data-value"))
            - (135252000 / (100000 * 1.02 * fx) - 1) * 100
        )
        < 1e-10
    )
    assert "실시간" not in widget.locator("#forex").inner_text()
    assert all(
        int(v) >= 59 for v in widget.locator("canvas").evaluate_all("els=>els.map(x=>x.dataset.samples)")
    )
    assert not any("/candles/" in url for url, _ in fixture.requests), (
        "Removed Upbit chart must not fetch candles"
    )
    baseline = None
    event_file = event_log
    if app_url and event_file is not None:
        assert event_file.exists(), "This run's instrumentation log is missing"
        baseline = event_file.read_text()
    now = page.evaluate("Date.now()")
    for symbol, price in (("BTCUSDT", 101000), ("ETHUSDT", 3100.5), ("KRW-BTC", 135252000)):
        send(widget, symbol, price, now)
    page.clock.run_for(400)
    assert widget.locator("#binance .price span").inner_text() == "101,000.00"
    assert widget.locator("#ethereum .price span").inner_text() == "3,100.50"
    assert (
        abs(
            float(widget.locator("#premium").get_attribute("data-value"))
            - (135252000 / (101000 * 1.02 * fx) - 1) * 100
        )
        < 1e-10
    )
    assert widget.locator(".crypto.fresh").count() == 2
    for packet in (
        "not json",
        json.dumps({"s": "DOGEUSDT", "c": "1", "E": now + 1}),
        json.dumps({"s": "BTCUSDT", "c": "-1", "E": now + 1}),
        json.dumps({"s": "BTCUSDT", "c": "1", "E": now - 60000}),
    ):
        widget.evaluate("p=>window.__quoteSockets.find(s=>s.url.includes('btcusdt@')).emit(p,false)", packet)
    page.clock.run_for(300)
    assert widget.locator("#binance .price span").inner_text() == "101,000.00"
    assert widget.locator("#ethereum .price span").inner_text() == "3,100.50"
    if baseline is not None:
        assert event_file.read_text() == baseline, "Quote updates re-entered Python"
    if app_url:
        assert page.get_by_text("데이터 모드", exact=True).count() == 0
        assert page.get_by_text("거래소", exact=True).count() == 0
        widget.evaluate("window.__quoteProbe='same-iframe'")
        page.get_by_role("tab", name="기술 지표", exact=True).click()
        page.get_by_text("기술지표 한눈에 보기", exact=True).wait_for()
        assert widget.evaluate("window.__quoteProbe") == "same-iframe"
        page.get_by_role("tab", name="시장 개요", exact=True).click()
        page.get_by_text("차트로 확인하기", exact=True).wait_for()
    assert widget.evaluate("document.querySelector('.note').getBoundingClientRect().bottom <= innerHeight")
    assert widget.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    widget.locator("#binance").screenshot(path=f"/tmp/btc-markets-btc-{width}.png")
    page.screenshot(path=f"/tmp/btc-markets-{width}.png")
    fixture.rest = False
    page.clock.fast_forward(16000)
    page.clock.run_for(400)
    assert widget.locator(".crypto.stale").count() == 2
    assert widget.locator("#premium").get_attribute("data-ready") == "false"
    assert "시세 지연" in widget.locator("#premium .status").inner_text()
    # Simulated transports emit no periodic packets. Let both watchdogs finish
    # any reconnect already triggered while checking staleness/tab navigation.
    for _ in range(15):
        if widget.evaluate(
            "['btcusdt@','api.upbit.com'].every(token=>window.__quoteSockets.filter(s=>s.url.includes(token)).at(-1)?.readyState===1)"
        ):
            break
        page.clock.run_for(1000)
    else:
        raise AssertionError("Quote transports never reopened")
    now = page.evaluate("Date.now()")
    send(widget, "BTCUSDT", 100000, now)
    send(widget, "ETHUSDT", 3000.25, now)
    page.clock.run_for(400)
    assert widget.locator("#binance.fresh").count() == 1
    assert widget.locator("#premium").get_attribute("data-ready") == "false", (
        "One fresh input cannot revive kimchi premium"
    )
    send(widget, "KRW-BTC", 132600000, now)
    page.clock.run_for(400)
    fx = float(widget.locator("#forex .price span").inner_text().replace(",", ""))
    assert (
        abs(
            float(widget.locator("#premium").get_attribute("data-value"))
            - (132600000 / (100000 * 1.02 * fx) - 1) * 100
        )
        < 1e-10
    )
    count = widget.evaluate("window.__quoteSockets.filter(s=>s.url.includes('btcusdt@')).length")
    widget.evaluate("window.__quoteSockets.filter(s=>s.url.includes('btcusdt@')).at(-1).close()")
    page.clock.run_for(1700)
    assert widget.evaluate("window.__quoteSockets.filter(s=>s.url.includes('btcusdt@')).length") == count + 1
    fixture.rest = True
    with page.expect_response(lambda r: "/ticker/24hr?symbols=" in r.url and r.status == 200):
        page.clock.fast_forward(11000)
    page.wait_for_timeout(100)
    page.clock.run_for(700)
    assert "5초 조회" in widget.locator("#binance .status").inner_text()
    assert all(
        int(v) <= 61 for v in widget.locator("canvas").evaluate_all("els=>els.map(x=>x.dataset.samples)")
    )
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
    )
    assert widget.evaluate("window.__quoteSockets.every(s=>s.readyState===3)")
    count = widget.evaluate("window.__quoteSockets.length")
    widget.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))"
    )
    page.clock.run_for(400)
    assert widget.evaluate("window.__quoteSockets.length") == count + 3
    assert not errors, errors
    cleanup(page, widget)
    return {
        "width": width,
        "mode": "embedded" if app_url else "standalone",
        "passed": True,
        "parent_analysis_checked": baseline is not None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url")
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
        results = [verify(browser, width, args.app_url, args.event_log) for width in (1440, 390)]
        browser.close()
    print(json.dumps(results))


if __name__ == "__main__":
    main()
