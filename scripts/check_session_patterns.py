"""Production move detection, attribution and native mobile cards, with injected feeds.

Browser times/transport shapes are controlled; this does not verify public feeds
or headline causation. No test-only hooks are added to the production widget.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, send, widget_html
from check_touch_charts import inspect, touch


class FlatHistory(MarketFixture):
    def route(self, route):
        if "klines" not in route.request.url:
            return super().route(route)
        now = self.page.evaluate("Date.now()")
        end = now // 60000 * 60000
        base = 3000 if "ETHUSDT" in route.request.url else 100000
        rows = [
            [end - (59 - i) * 60000, base, base, base, str(base), "10", end - (59 - i) * 60000 + 59999]
            for i in range(60)
        ]
        route.fulfill(json=rows, headers={"Access-Control-Allow-Origin": "*"})


def host(page):
    page.evaluate("""()=>{
      const node=document.createElement('section');node.id='btc-move-alerts';node.hidden=true;document.body.append(node);
      const news=document.createElement('div');news.id='btc-news-bridge';news.hidden=true;document.body.append(news);
    }""")


def candidates(page):
    page.evaluate("""()=>{
      const root=document.getElementById('btc-news-bridge');root.replaceChildren();
      for(const [title,assets,direction,age,fresh,protocol] of [
        ['Bitcoin ETF inflows','BTCUSDT',1,180000,0,'https:'],
        ['Bitcoin oil spike','BTCUSDT',-1,180000,0,'https:'],
        ['Ethereum hack','ETHUSDT',-1,180000,0,'https:'],
        ['Future Bitcoin ETF','BTCUSDT',1,-60000,0,'https:'],
        ['Old Bitcoin ETF','BTCUSDT',1,1900000,0,'https:'],
        ['Stale Bitcoin ETF','BTCUSDT',1,180000,130000,'https:'],
        ['Unsafe Bitcoin ETF','BTCUSDT',1,180000,0,'javascript:']]) {
        const a=document.createElement('a');a.textContent=title;a.href=protocol==='https:' ? 'https://example.com/'+encodeURIComponent(title) : 'javascript:alert(1)';
        Object.assign(a.dataset,{assets,direction:String(direction),published:String(Date.now()-age),fetched:String(Date.now()-fresh),source:'Injected source'});root.append(a);
      }
    }""")


def standalone(browser):
    page = browser.new_page(viewport={"width": 390, "height": 1000})
    page.clock.install(time=datetime.now(timezone.utc).replace(second=1, microsecond=0))
    install_quote_transport(page)
    fixture = FlatHistory(page)
    page.route(
        "http://widget.test/", lambda route: route.fulfill(body=widget_html(), content_type="text/html")
    )
    page.goto("http://widget.test/")
    page.locator('#binance[data-history="ready"]').wait_for()
    page.clock.run_for(200)
    host(page)
    candidates(page)
    now = page.evaluate("Date.now()")
    send(page.main_frame, "BTCUSDT", 100600, now)
    page.clock.run_for(100)
    card = page.locator('.btc-move-card[data-symbol="BTCUSDT"]')
    assert "약 1분 +0.60%" in card.inner_text()
    assert card.locator("a").all_text_contents() == ["Bitcoin ETF inflows ↗"]
    detected = card.get_attribute("data-detected")
    send(page.main_frame, "BTCUSDT", 100700, now + 100)
    page.clock.run_for(100)
    assert card.get_attribute("data-detected") == detected
    # Same event does not continuously rewrite an aria-live card on every tick.
    assert "+0.60%" in card.inner_text()
    send(page.main_frame, "BTCUSDT", 99000, page.evaluate("Date.now()"))
    page.clock.run_for(100)
    assert "급하락" in card.inner_text()
    assert card.locator("a").all_text_contents() == ["Bitcoin oil spike ↗"]
    send(page.main_frame, "ETHUSDT", 2970, page.evaluate("Date.now()"))
    page.clock.run_for(100)
    eth = page.locator('.btc-move-card[data-symbol="ETHUSDT"]')
    assert eth.locator("a").all_text_contents() == ["Ethereum hack ↗"]
    assert page.locator(".btc-move-card").count() == 2
    assert page.evaluate("window.__quoteSockets.length") == 3
    # Stale/unsafe news does not become a verified cause; bridge replacement clears candidates.
    page.evaluate("document.getElementById('btc-news-bridge').remove()")
    page.clock.run_for(1100)
    assert "원인 확인 중" in card.inner_text()
    assert card.locator("a").count() == 0
    # A long transport gap cannot turn its first reconnect price into a burst.
    fixture.rest = False
    page.wait_for_timeout(100)
    page.clock.fast_forward(180000)
    page.clock.run_for(100)
    assert page.locator("#btc-move-alerts").is_hidden()
    send(page.main_frame, "BTCUSDT", 110000, page.evaluate("Date.now()"))
    page.clock.run_for(100)
    assert page.locator("#btc-move-alerts").is_hidden()
    # Stale and future events cannot raise an alert, even if the price passes the threshold.
    send(page.main_frame, "ETHUSDT", 3300, page.evaluate("Date.now()") + 20000)
    page.clock.run_for(100)
    assert page.locator("#btc-move-alerts").is_hidden()
    cleanup(page, page.main_frame)
    return {
        "standalone": "passed",
        "dedupe": "passed",
        "asset_direction_time_filters": "passed",
        "gap_future_stale": "passed",
        "extra_sockets": 0,
    }


def embedded(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    # Align controlled browser time to a minute, after server news timestamps.
    page.clock.install(
        time=(datetime.now(timezone.utc) + timedelta(minutes=1)).replace(second=1, microsecond=0)
    )
    install_quote_transport(page)
    FlatHistory(page)
    page.goto(url)
    page.get_by_text("최근 횡보 흐름", exact=True).wait_for(timeout=45000)
    page.locator("#btc-news-bridge a").first.wait_for(state="attached", timeout=15000)
    assert page.locator(".btc-pattern-card").count() == 1
    assert "KST" in page.locator(".btc-pattern-grid").inner_text()
    crypto = next(frame for frame in page.frames if frame.locator("#binance").count())
    crypto.locator('#binance[data-history="ready"]').wait_for()
    # Both Binance assets arrive on the existing socket.
    now = crypto.evaluate("Date.now()")
    send(crypto, "BTCUSDT", 101200, now)
    send(crypto, "ETHUSDT", 3000, now)
    card = page.locator('.btc-move-card[data-symbol="BTCUSDT"]')
    card.wait_for()
    assert "급상승" in card.inner_text() and "관련 가능" in card.inner_text()
    assert "원인인지는 확인되지" in card.inner_text()
    assert card.locator("a").count() > 0
    assert "유가 급등" not in card.inner_text()
    assert page.locator("iframe").count() == 1
    baseline = event_log.read_text() if event_log else None
    sockets = crypto.evaluate("window.__quoteSockets.length")
    card.scroll_into_view_if_needed()
    page.screenshot(path=f"/tmp/btc-patterns-alert-{width}.png")
    cdp = context.new_cdp_session(page)
    box = card.bounding_box()
    scroller = page.locator('[data-testid="stMain"]')
    before = scroller.evaluate("e=>e.scrollTop")
    x, y = box["x"] + box["width"] / 2, max(100, min(800, box["y"] + box["height"] / 2))
    touch(cdp, "touchStart", [(x, y)])
    for step in range(1, 6):
        touch(cdp, "touchMove", [(x, y - 120 * step / 5)])
        page.wait_for_timeout(30)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(150)
    assert scroller.evaluate("e=>e.scrollTop") > before + 20, "Alert trapped page scrolling"
    # A real touch on the existing chart still reads prices and preserves axes.
    inspect(page, cdp, page.locator(".js-plotly-plot:visible").first, event_log, "market with alert")
    page.get_by_role("radio", name="상세", exact=True).tap()
    page.get_by_text("표시할 봉 수", exact=True).wait_for()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not page.locator('[data-testid="stException"]').count()
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    if baseline is not None:
        assert event_log.read_text() == baseline, "Alert/card/touch reran parent analysis"
    # Hidden pages remove the native banner and all quote sockets.
    crypto.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
    )
    assert page.locator("#btc-move-alerts").is_hidden()
    cleanup(page, page.main_frame)
    context.close()
    return {
        "width": width,
        "patterns": "passed",
        "move_news": "passed",
        "touch_scroll_hover": "passed",
        "parent_analysis_checked": baseline is not None,
        "extra_iframes": 0,
    }


def five_minutes_and_expiry(browser):
    page = browser.new_page(viewport={"width": 390, "height": 1000})
    page.clock.install(time=datetime.now(timezone.utc).replace(second=1, microsecond=0))
    install_quote_transport(page)
    FlatHistory(page)
    page.route(
        "http://widget.test/", lambda route: route.fulfill(body=widget_html(), content_type="text/html")
    )
    page.goto("http://widget.test/")
    page.locator('#binance[data-history="ready"]').wait_for()
    host(page)
    # Each minute moves <0.5%, but the rolling five-minute move exceeds 1%.
    for seconds in range(10, 301, 10):
        page.clock.run_for(10000)
        now = page.evaluate("Date.now()")
        send(page.main_frame, "BTCUSDT", 100000 * (1 + seconds * 0.00007), now)
        send(page.main_frame, "ETHUSDT", 3000, now)
        page.clock.run_for(100)
    assert "약 5분" in page.locator('.btc-move-card[data-symbol="BTCUSDT"]').inner_text()
    # Quotes stay fresh, while the captured event expires without new movement.
    for _ in range(70):
        page.clock.run_for(10000)
        now = page.evaluate("Date.now()")
        send(page.main_frame, "BTCUSDT", 102100, now)
        send(page.main_frame, "ETHUSDT", 3000, now)
        page.clock.run_for(100)
    assert page.locator("#btc-move-alerts").is_hidden()
    assert page.evaluate("window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance')).length") == 1
    cleanup(page, page.main_frame)
    return {"rolling_five_minutes": "passed", "fresh_quote_event_expiry": "passed", "binance_connections": 1}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url")
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        print(json.dumps(standalone(browser)), flush=True)
        print(json.dumps(five_minutes_and_expiry(browser)), flush=True)
        if args.app_url:
            for width in (390, 820, 1440):
                print(json.dumps(embedded(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
