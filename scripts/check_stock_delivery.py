"""REST-only stock delivery, DOM recovery, cached prices and desktop zoom controls."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, cleanup
from check_chart_gestures import ranges, region_box, gesture_check


def verify(browser, width, url, events):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    MarketFixture(page)
    before = events.read_text() if events else None
    page.goto(url)
    page.get_by_role("button", name="삼성전기 차트 열기", exact=True).wait_for(timeout=60000)
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.btc-macro-card[data-quote-symbol]')].length===11&&[...document.querySelectorAll('.btc-macro-card[data-quote-symbol] [data-quote-field=price]')].every(e=>e.textContent!=='—')"
    )
    if before is not None:
        assert events.read_text() == before, "Quote delivery collected historical candles"
    assert not page.locator(".js-plotly-plot").count()
    bridge = next(frame for frame in page.frames if frame.locator("#binance").count())
    # No Yahoo tick is emitted. A REST-only price must restore a native overwrite
    # without replacing the entire card on a native fragment timer.
    page.evaluate(
        """()=>{window.__deliveryCard=document.querySelector('#macro-aapl');window.__deliveryCard.querySelector('[data-quote-field=price]').textContent='—';}"""
    )
    page.wait_for_function(
        "()=>document.querySelector('#macro-aapl [data-quote-field=price]')?.textContent==='$343.46'"
    )
    assert page.evaluate("window.__deliveryCard===document.querySelector('#macro-aapl')")
    page.evaluate("""()=>{
      const node=document.querySelector('#btc-quote-snapshot'),rows=JSON.parse(node.dataset.quotes),row=rows.find(r=>r.symbol==='AAPL');
      Object.assign(row,{price:400.25,asOf:Date.now()-1000,fetched:Date.now(),regularPrice:390,regularAsOf:Date.now()-30000,session:'post',change:(400.25/390-1)*100});
      node.dataset.quotes=JSON.stringify(rows);
    }""")
    page.wait_for_function(
        "()=>document.querySelector('#macro-aapl [data-quote-field=price]')?.textContent==='$400.25'"
    )
    assert "장후" in page.locator("#macro-aapl [data-quote-field=status]").inner_text()
    assert page.locator("#macro-aapl [data-quote-field=regular]").inner_text() == "390.00"
    page.evaluate("""()=>{
      const node=document.querySelector('#btc-quote-snapshot'),rows=JSON.parse(node.dataset.quotes),row=rows.find(r=>r.symbol==='AAPL');
      Object.assign(row,{price:399,asOf:Date.now()-5000,regularPrice:395,regularAsOf:Date.now()-10000});
      node.dataset.quotes=JSON.stringify(rows);
    }""")
    page.wait_for_function(
        "()=>document.querySelector('#macro-aapl [data-quote-field=regular]')?.textContent==='395.00'"
    )
    assert page.locator("#macro-aapl [data-quote-field=price]").inner_text() == "$400.25"
    page.get_by_role("button", name="애플 차트 열기", exact=True).click()
    page.locator("#btc-chart-reader").wait_for(timeout=45000)
    page.wait_for_function(
        "()=>document.querySelector('.board-detail [data-quote-field=price]')?.textContent==='$400.25'"
    )
    page.wait_for_function(
        "()=>document.querySelector('#btc-chart-reader [data-field=current]')?.textContent==='400.25'"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    page.wait_for_function("()=>document.querySelector('.js-plotly-plot')?._fullLayout?.yaxis4")
    baseline = events.read_text() if events else None

    def xspan():
        limits = ranges(plot)["x"]
        return limits[1] - limits[0]

    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.5
    original = xspan()
    page.mouse.move(x, y)
    page.mouse.wheel(0, -120)
    page.wait_for_timeout(450)
    assert xspan() < original * 0.85
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(450)
    assert xspan() > original * 0.85
    page.keyboard.down("Shift")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + box["width"] * 0.14, y, steps=12)
    page.mouse.up()
    page.keyboard.up("Shift")
    page.wait_for_timeout(350)
    assert xspan() < original * 0.8
    reader = page.locator("#btc-chart-reader")
    reader.get_by_role("button", name="확대·축소", exact=True).click()
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    zoomed = xspan()
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - box["width"] * 0.17, y, steps=12)
    page.mouse.up()
    page.wait_for_timeout(350)
    assert xspan() > zoomed * 1.3
    reader.get_by_role("button", name="확대·축소", exact=True).click()
    box = region_box(page, plot)
    before_y = ranges(plot)["y"]
    axis_x, axis_y = box["x"] + box["width"] + 15, box["y"] + box["height"] * 0.5
    page.mouse.move(axis_x, axis_y)
    page.mouse.down()
    page.mouse.move(axis_x, axis_y - box["height"] * 0.12, steps=12)
    page.mouse.up()
    page.wait_for_timeout(350)
    assert ranges(plot)["y"] != before_y
    assert reader.get_by_role("button", name="오토", exact=True).get_attribute("aria-pressed") == "false"
    reader.get_by_role("button", name="오토", exact=True).click()
    cdp = context.new_cdp_session(page)
    gesture_check(page, cdp, plot, events, "REST-only stock")
    last = plot.locator(".nsewdrag").last
    last.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
    box = last.bounding_box()
    span = xspan()
    x, y = box["x"] + box["width"] * 0.45, box["y"] + box["height"] + 12
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + box["width"] * 0.12, y, steps=12)
    page.mouse.up()
    page.wait_for_timeout(350)
    assert xspan() < span * 0.8
    if baseline is not None:
        assert events.read_text() == baseline, "Local chart manipulation requested Python work"
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not errors, errors
    page.screenshot(path=f"/tmp/btc-105-stock-interaction-{width}.png")
    cleanup(page, bridge)
    context.close()
    return {
        "width": width,
        "rest_only_delivery": True,
        "same_card_restored": True,
        "after_hours_separate": True,
        "wheel_shift_toggle_axis_zoom": True,
        "touch_pan_pinch_auto": True,
        "errors": errors,
    }


def verify_cache(browser, url):
    results = []
    for currency, age, expected in (
        ("USD", 5000, "$351.25"),
        ("KRW", 5000, "$343.46"),
        ("USD", 8 * 86400000, "$343.46"),
    ):
        context = browser.new_context(viewport={"width": 390, "height": 1000})
        page = context.new_page()
        install_quote_transport(page)
        MarketFixture(page)
        page.add_init_script(
            """try{localStorage.setItem('market-last-quotes-v1',JSON.stringify([{
          symbol:'AAPL',currency:"""
            + json.dumps(currency)
            + """,price:351.25,asOf:Date.now()-"""
            + str(age)
            + """,
          change:1,session:'post',regularPrice:350,regularAsOf:Date.now()-3600000
        }]))}catch(_){}"""
        )
        page.goto(url)
        page.frame_locator("iframe").locator("#binance").wait_for(state="attached", timeout=60000)
        page.wait_for_function(
            "p=>document.querySelector('#macro-aapl [data-quote-field=price]')?.textContent===p", arg=expected
        )
        if currency == "USD" and age == 5000:
            assert "최근 수신" in page.locator("#macro-aapl [data-quote-field=status]").inner_text()
            assert "장후" in page.locator("#macro-aapl [data-quote-field=status]").inner_text()
        results.append({"currency": currency, "age_ms": age, "price": expected})
        bridge = next(frame for frame in page.frames if frame.locator("#binance").count())
        cleanup(page, bridge)
        context.close()
    return {"cache_validated_and_labeled": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--widths", type=int, nargs="+", default=[390, 820, 1440])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        print(json.dumps(verify_cache(browser, args.app_url)), flush=True)
        browser.close()
