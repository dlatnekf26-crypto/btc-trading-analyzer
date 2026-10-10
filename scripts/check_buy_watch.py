"""Real app: conditional watch prices, quote distance and touch with fixtures."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport
from check_touch_charts import inspect


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    install_quote_transport(page)
    fixture = MarketFixture(page)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    card = page.locator("#btc-buy-watch")
    card.wait_for(timeout=45000)
    page.wait_for_function("()=>document.querySelector('.js-plotly-plot')?.data?.length > 0")
    crypto = next(frame for frame in page.frames if frame.locator("#binance").count())
    crypto.locator('#binance[data-history="ready"]').wait_for()
    fixture.rest = False
    data = card.evaluate("e=>({...e.dataset})")
    low, high, stop = float(data["low"]), float(data["high"]), float(data["stop"])
    assert 90000 < stop < low < high < 100000
    assert "관망 · 종합 신호" in page.locator(".btc-signal-label").inner_text()
    assert "도달해도 하락 진정" in card.inner_text()
    assert "자동 매수 신호가 아니에요" in card.inner_text()
    original = card.locator(".btc-buy-watch-price").inner_text()
    band = (data["low"], data["high"])
    sockets = crypto.evaluate("window.__quoteSockets.length")
    assert page.locator("iframe").count() == 1
    # Event-driven updates through the existing production socket, no Python.
    baseline = event_log.read_text() if event_log else None

    def emit(price, offset=0):
        crypto.evaluate(
            """([price,offset])=>{
          const socket=window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance')&&s.readyState===1).at(-1);
          socket.emit(JSON.stringify({data:{e:'aggTrade',s:'BTCUSDT',p:String(price),E:Date.now()+offset}}));
        }""",
            [price, offset],
        )

    def state(name):
        page.wait_for_function(
            "name=>document.querySelector('#btc-buy-watch')?.dataset.status===name", arg=name
        )

    emit(100000)
    state("above")
    assert "%" in card.locator(".btc-buy-watch-distance").inner_text()
    emit((low + high) / 2)
    state("inside")
    assert "하락 진정" in card.locator(".btc-buy-watch-distance").inner_text()
    assert "관망 · 종합 신호" in page.locator(".btc-signal-label").inner_text()
    emit((low + stop) / 2)
    state("below")
    assert "더 저렴하다고 매수하지" in card.locator(".btc-buy-watch-distance").inner_text()
    assert card.locator(".btc-buy-watch-price").inner_text() == original
    assert card.evaluate("e=>[e.dataset.low,e.dataset.high]") == list(band)
    card.scroll_into_view_if_needed()
    assert card.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
    assert page.locator('[data-testid="stMain"]').evaluate("e=>e.scrollWidth<=e.clientWidth+1")
    page.screenshot(path=f"/tmp/btc-buy-watch-{width}.png")
    plot = page.locator(".js-plotly-plot:visible").first
    inspect(page, context.new_cdp_session(page), plot, event_log, "buy watch market")
    emit(stop - 10)
    state("invalid")
    assert card.locator(".btc-buy-watch-price").inner_text() == "가격대 재평가 필요"
    emit((low + high) / 2)
    state("invalid")
    assert card.locator(".btc-buy-watch-price").inner_text() == "가격대 재평가 필요"
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    assert page.locator("iframe").count() == 1
    assert not errors and not page.locator('[data-testid="stException"]').count(), errors
    if baseline is not None:
        assert event_log.read_text() == baseline
    result = {
        "width": width,
        "band": [low, high],
        "signal": "관망",
        "states": "above/inside/below/invalid-latched",
        "touch": "hover/no-zoom/scroll passed",
        "extra_connections": 0,
        "python_tick_calls": 0,
    }
    cleanup(page, crypto)
    context.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        try:
            for width in (390, 820, 1440):
                print(
                    json.dumps(verify(browser, width, args.url, args.event_log), ensure_ascii=False),
                    flush=True,
                )
        finally:
            browser.close()
