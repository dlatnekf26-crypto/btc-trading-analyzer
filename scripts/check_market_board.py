"""Real browser checks for the quote board, modal lifecycle and shared feed."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, send_macro, cleanup
from check_chart_gestures import gesture_check
from check_touch_charts import inspect


def verify(browser, width, url, events):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    MarketFixture(page)
    baseline = events.read_text() if events else None
    page.goto(url)
    page.get_by_role("button", name="비트코인 차트 열기", exact=True).wait_for(timeout=60000)
    page.wait_for_function(
        "()=>document.querySelector('[data-quote-symbol=BTCUSDT] [data-quote-field=price]')?.textContent==='$100,000.00'"
    )
    page.wait_for_timeout(1000)
    assert not page.locator(".js-plotly-plot").count()
    if baseline is not None:
        assert events.read_text() == baseline, "Landing page collected/analyzed history"
    bridge = next(frame for frame in page.frames if frame.locator("#binance").count())
    bridge.evaluate("""window.__boardToken=Math.random();window.__boardFeed=setInterval(()=>{
      const now=Date.now(),b=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);
      for(const [s,c] of [['BTCUSDT','100000'],['ETHUSDT','3000.25'],['SOLUSDT','150.25'],['XRPUSDT','1.1532']])b?.emit(JSON.stringify({data:{s,c,P:'2.34',E:now}}));
      window.__quoteSockets.find(s=>s.url.includes('upbit')&&s.readyState===1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:.01,timestamp:now}),true);
    },1000)""")
    token = bridge.evaluate("window.__boardToken")
    history_requests = bridge.evaluate("window.__quoteFetches.filter(r=>r.url.includes('klines')).length")
    assert page.locator("[data-quote-symbol=BTCUSDT] [data-quote-field=high]").inner_text() == "103,000.00"
    assert page.locator("[data-quote-symbol=XRPUSDT] [data-quote-field=price]").inner_text() == "$1.1532"
    assert page.locator("[data-reference=fx] b").inner_text() == "₩1,300.00"
    assert (
        page.locator("[data-quote-symbol=BTCUSDT] [data-quote-field=change]").evaluate(
            "e=>getComputedStyle(e).color"
        )
        == "rgb(239, 101, 114)"
    )
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    boxes = page.locator(".board-sentiment,.board-fx").evaluate_all(
        "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,height:r.height,scroll:e.scrollHeight,client:e.clientHeight}})"
    )
    assert len(boxes) >= 7
    for i, a in enumerate(boxes):
        assert a["scroll"] <= a["client"] + 1, boxes
        for b in boxes[i + 1 :]:
            assert (
                a["right"] <= b["x"] or b["right"] <= a["x"] or a["bottom"] <= b["y"] or b["bottom"] <= a["y"]
            ), boxes
    page.screenshot(path=f"/tmp/btc-board-{width}.png", full_page=True)
    for code, name, symbol in (
        ("BTC", "비트코인", "BTCUSDT"),
        ("ETH", "이더리움", "ETHUSDT"),
        ("SOL", "솔라나", "SOLUSDT"),
        ("XRP", "리플", "XRPUSDT"),
        ("NQ", "나스닥100 선물", "NQ=F"),
        ("KOSPI", "코스피", "^KS11"),
        ("MSTR", "스트래티지", "MSTR"),
        ("GOOGL", "알파벳", "GOOGL"),
        ("TSLA", "테슬라", "TSLA"),
        ("META", "메타", "META"),
        ("HYUNDAI", "현대차", "005380.KS"),
        ("LGES", "LG에너지솔루션", "373220.KS"),
        ("OIL", "WTI 원유 선물", "CL=F"),
        ("TNX", "미국채 10년 금리", "^TNX"),
        ("TYX", "미국채 30년 금리", "^TYX"),
    ):
        button = page.get_by_role("button", name=name + " 차트 열기", exact=True)
        button.scroll_into_view_if_needed()
        box = button.bounding_box()
        assert box["height"] >= 70, "Quote row touch target is too small"
        page.touchscreen.tap(box["x"] + box["width"] * 0.4, box["y"] + 30)
        page.locator("#btc-chart-reader").wait_for(timeout=60000)
        page.wait_for_function(
            "s=>document.querySelector('#btc-chart-reader')?.dataset.symbol===s", arg=symbol
        )
        dialog = page.get_by_role("dialog")
        rect = dialog.bounding_box()
        assert rect["x"] >= 0 and rect["x"] + rect["width"] <= width + 1, rect
        assert rect["y"] >= 0 and rect["y"] + rect["height"] <= 1001, rect
        assert f"market={code}" in page.url and "view=chart" in page.url
        assert bridge.evaluate("window.__boardToken") == token
        if code in ("NQ", "KOSPI"):
            now = page.evaluate("Date.now()")
            send_macro(
                bridge,
                symbol,
                22500.25 if code == "NQ" else 2850.25,
                now,
                currency="USD" if code == "NQ" else "KRW",
            )
            page.wait_for_function(
                "s=>document.querySelector('.board-detail[data-quote-symbol=\"'+s+'\"] [data-quote-field=price]')?.textContent.includes('50.25')",
                arg=symbol,
            ) if code == "KOSPI" else page.wait_for_function(
                "()=>document.querySelector('.board-detail [data-quote-field=price]')?.textContent==='22,500.25'"
            )
        if code == "BTC":
            plot = page.locator(".js-plotly-plot:visible").first
            page.wait_for_function("()=>document.querySelector('.js-plotly-plot')?._fullLayout?.yaxis4")
            cdp = context.new_cdp_session(page)
            gesture_check(page, cdp, plot, events, "board detail")
            inspect(page, cdp, plot, events, "board detail scroll")
            dialog.evaluate("e=>e.scrollTop=e.scrollHeight")
            page.wait_for_timeout(200)
            assert dialog.evaluate("e=>e.scrollTop>500")
            dialog.evaluate("e=>e.scrollTop=0")
            page.screenshot(path=f"/tmp/btc-board-detail-{width}.png")
        page.get_by_role("button", name="Close", exact=True).tap()
        page.get_by_role("dialog").wait_for(state="detached")
        page.wait_for_timeout(350)
        assert "view=chart" not in page.url
        assert page.evaluate("getComputedStyle(document.documentElement).overflow!=='hidden'")
    assert len(page.locator("iframe").all()) == 1
    assert bridge.evaluate("window.__quoteSockets.filter(s=>s.readyState===1).length") == 3
    assert (
        bridge.evaluate("window.__quoteFetches.filter(r=>r.url.includes('klines')).length")
        == history_requests
    )
    assert not errors, errors
    before = events.read_text() if events else None
    page.wait_for_timeout(3000)
    if before is not None:
        assert events.read_text() == before, "Closed detail kept analyzing in the background"
    cleanup(page, bridge)
    context.close()
    return {
        "width": width,
        "landing_history_jobs": 0,
        "fifteen_card_details": True,
        "overview_no_overlap": True,
        "touch_and_scroll": True,
        "shared_bridge": True,
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--widths", nargs="+", type=int, default=[390, 820, 1440])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
