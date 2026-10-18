"""Closed-market prices, unchanged graphs and unavailable quote reader recovery."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, cleanup


def verify(browser, width, url, events=None, unavailable=False):
    context = browser.new_context(viewport={"width": width, "height": 1000}, has_touch=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    MarketFixture(page)
    before = events.read_text() if events else None
    page.goto(url)
    page.frame_locator("iframe").locator("#binance").wait_for(state="attached", timeout=60000)
    bridge = next(frame for frame in page.frames if frame.locator("#binance").count())
    if unavailable:
        page.get_by_role("button", name="애플 차트 열기", exact=True).click()
        page.locator("#btc-chart-reader").wait_for(timeout=45000)
        page.wait_for_function(
            "()=>document.querySelector('#btc-chart-reader [data-field=current]')?.textContent!=='—'"
        )
        price = page.locator("#btc-chart-reader [data-field=current]").inner_text()
        page.wait_for_timeout(3500)
        assert page.locator("#btc-chart-reader [data-field=current]").inner_text() == price
        assert "마지막 확정 봉" in page.locator("#btc-chart-reader [data-current-status]").inner_text()
        assert page.locator("#btc-chart-reader [data-current-label]").inner_text() == "마지막 가격"
    else:
        page.wait_for_function(
            "()=>document.querySelector('#macro-aapl [data-quote-field=price]')?.textContent==='$343.46'"
        )
        if before is not None:
            assert events.read_text() == before, "Opening the board collected candle history"
        assert not page.locator(".js-plotly-plot").count()
        page.evaluate("""()=>{
          window.__setClosedQuote=update=>{
            const target=document.querySelector('#btc-quote-snapshot'),input=JSON.parse(window.__closedPayload||target.dataset.quotes);
            Object.assign(input.find(r=>r.symbol==='AAPL'),update);window.__closedPayload=JSON.stringify(input);target.dataset.quotes=window.__closedPayload;
          };
          // Pin only this controlled input while native fragments continue running.
          new MutationObserver(()=>{const target=document.querySelector('#btc-quote-snapshot');if(target&&target.dataset.quotes!==window.__closedPayload)target.dataset.quotes=window.__closedPayload;}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['data-quotes']});
          window.__setClosedQuote({marketState:'closed',stateUntil:Date.now()+3600000,price:350,asOf:Date.now()-2000,regularPrice:343.46,regularAsOf:Date.now()-5000,session:'post',change:(350/343.46-1)*100});
        }""")
        page.wait_for_function(
            "()=>document.querySelector('#macro-aapl [data-quote-field=price]')?.textContent==='$350.00'&&document.querySelector('#macro-aapl [data-quote-field=status]')?.textContent.includes('장 마감')"
        )
        assert "장후 마지막 거래가" in page.locator("#macro-aapl [data-quote-field=status]").inner_text()
        assert "KST" in page.locator("#macro-aapl [data-quote-field=status]").inner_text()
        assert page.locator("#macro-aapl [data-quote-field=regular]").inner_text() == "343.46"
        # An identical quote with a newer fetch stamp must keep its SVG object.
        page.evaluate("""()=>{window.__closedGraph=document.querySelector('#macro-aapl svg');
          window.__setClosedQuote({fetched:Date.now()});}""")
        page.wait_for_timeout(400)
        assert page.evaluate("window.__closedGraph===document.querySelector('#macro-aapl svg')")
        page.get_by_role("button", name="애플 차트 열기", exact=True).click()
        page.wait_for_function(
            "()=>document.querySelector('#btc-chart-reader [data-field=current]')?.textContent==='350.00'",
            timeout=45000,
        )
        assert page.locator("#btc-chart-reader [data-current-label]").inner_text() == "마지막 가격"
        # A failed refresh carries no replacement price and cannot erase it.
        page.evaluate("""()=>{window.__setClosedQuote({error:'자료원 연결 지연'});}""")
        page.wait_for_function(
            "()=>document.querySelector('#macro-aapl [data-quote-field=status]')?.textContent.includes('갱신 지연')"
        )
        assert page.locator("#btc-chart-reader [data-field=current]").inner_text() == "350.00"
        page.evaluate(
            """()=>{window.__setClosedQuote({marketState:'regular',stateUntil:Date.now()+3600000,session:'regular',error:'',price:351,asOf:Date.now(),fetched:Date.now(),regularPrice:351,regularAsOf:Date.now()});}"""
        )
        page.wait_for_function(
            "()=>document.querySelector('#btc-chart-reader [data-field=current]')?.textContent==='351.00'"
        )
        assert "장 마감" not in page.locator("#macro-aapl [data-quote-field=status]").inner_text()
        assert page.locator("#btc-chart-reader [data-current-label]").inner_text() == "현재 가격"
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not errors, errors
    page.screenshot(path=f"/tmp/btc-109-closed-{width}-{'unavailable' if unavailable else 'normal'}.png")
    cleanup(page, bridge)
    context.close()
    return {"width": width, "unavailable_quote": unavailable, "last_price_kept": True, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--widths", type=int, nargs="+", default=[390, 820, 1440])
    parser.add_argument("--unavailable", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(
                json.dumps(verify(browser, width, args.app_url, args.event_log, args.unavailable)), flush=True
            )
        browser.close()
