"""Integrated RSI/MACD values, live update batching and touch on every subplot."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_chart_gestures import touch, ranges, gesture_check
from check_live_widget import select_market, MarketFixture, install_quote_transport, cleanup


FIELDS = ("rsi", "macd", "macd_signal", "macd_hist")
PURE = (Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/browser/candles.js").read_text()


def subplot(page, plot, row):
    region = plot.locator(".nsewdrag").nth(row)
    region.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
    page.wait_for_timeout(100)
    return region.bounding_box()


def verify(browser, width, url, events):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.frame_locator("iframe").locator("#binance").wait_for(state="attached", timeout=60000)
    page.locator("#btc-chart-reader").wait_for(timeout=60000)
    widget = next(f for f in page.frames if f.locator("#binance").count())
    cdp = context.new_cdp_session(page)
    widget.evaluate("""window.__oscAlive=setInterval(()=>{
      const now=Date.now(),s=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);
      for(const [symbol,p] of [['BTCUSDT',100000],['ETHUSDT',3000],['SOLUSDT',150],['XRPUSDT',1.15]])s?.emit(JSON.stringify({data:{s:symbol,c:String(p),E:now,P:'1'}}));
      window.__quoteSockets.find(s=>s.url.includes('upbit')&&s.readyState===1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:.01,timestamp:now}),true);
    },1000)""")
    for tf, label in (
        ("5m", "5분"),
        ("15m", "15분"),
        ("1h", "1시간"),
        ("4h", "4시간"),
        ("1d", "일봉"),
        ("1w", "주봉"),
        ("1M", "월봉"),
    ):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "tf=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.timeframe===tf&&p._fullLayout.yaxis4)",
            arg=tf,
        )
        plot = page.locator(".js-plotly-plot:visible").first
        assert plot.locator(".nsewdrag").count() == 4
        assert plot.evaluate("p=>p._fullLayout.yaxis3.range[0]===0&&p._fullLayout.yaxis3.range[1]===100")
        for row, name in ((2, "RSI"), (3, "MACD")):
            box = subplot(page, plot, row)
            x = box["x"] + box["width"] * 0.55
            y = box["y"] + box["height"] * 0.5
            baseline = events.read_text() if events else None
            touch(cdp, "touchStart", [(x, y)])
            page.wait_for_timeout(400)
            assert name in plot.locator(".btc-crosshair-price").inner_text()
            at = page.locator("#btc-chart-reader").get_attribute("data-at")
            touch(cdp, "touchMove", [(x + box["width"] * 0.15, y)])
            page.wait_for_timeout(90)
            assert page.locator("#btc-chart-reader").get_attribute("data-at") != at
            touch(cdp, "touchEnd")
            if baseline is not None:
                assert events.read_text() == baseline
    page.get_by_role("radio", name="1시간", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.timeframe==='1h'")
    page.wait_for_function(
        "()=>{const ps=[...document.querySelectorAll('.js-plotly-plot')].filter(p=>p.getClientRects().length);return ps.length===1&&ps[0].layout?.meta?.btcLive?.timeframe==='1h'&&ps[0]._fullLayout.yaxis4;}"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    seed = page.locator("#btc-chart-seed").evaluate("e=>JSON.parse(e.dataset.seeds)")
    at = seed["frames"]["1h"]["end"]
    page.evaluate(
        """()=>{window.__oscCalls=0;const old=Plotly.update;Plotly.update=function(...a){window.__oscCalls++;return old.apply(this,a);};}"""
    )
    for i in (1, 2):
        price = 100000 + i * 100
        k = {"at": at, "end": at + 3600000, "row": [at, 100000, 102000, 98000, price, 18]}
        expected = page.evaluate(
            "input=>{" + PURE + "return LiveCandles.advance(input.seed,input.k,input.cfg).features}",
            {"seed": seed["frames"]["1h"], "cfg": seed["cfg"], "k": k},
        )
        widget.evaluate(
            """({at,price})=>{const now=Date.now(),s=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);s.emit(JSON.stringify({data:{e:'kline',E:now,s:'BTCUSDT',k:{s:'BTCUSDT',i:'1h',t:at,T:at+3600000-1,o:'100000',h:'102000',l:'98000',c:String(price),v:'18',x:false}}}));}""",
            {"at": at, "price": price},
        )
        page.wait_for_function(
            "p=>document.querySelector('.js-plotly-plot')?.dataset.livePrice===String(p)", arg=price
        )
        actual = plot.evaluate(
            """p=>Object.fromEntries(Object.entries(p.layout.meta.btcLive.overlays).map(([i,f])=>[f,p.data[i].y.at(-1)]))"""
        )
        for field in FIELDS:
            assert abs(actual[field] - expected[field]) <= max(1e-8, abs(expected[field]) * 1e-9), (
                field,
                actual[field],
                expected[field],
            )
        page.wait_for_timeout(550)
    assert page.evaluate("window.__oscCalls") == 2, page.evaluate("window.__oscCalls")
    # A duplicate candle carries a new event time, without a new chart draw.
    widget.evaluate(
        """at=>{const now=Date.now(),s=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);s.emit(JSON.stringify({data:{e:'kline',E:now,s:'BTCUSDT',k:{s:'BTCUSDT',i:'1h',t:at,T:at+3600000-1,o:'100000',h:'102000',l:'98000',c:'100200',v:'18',x:false}}}));}""",
        at,
    )
    page.wait_for_timeout(650)
    assert page.evaluate("window.__oscCalls") == 2
    gesture_check(page, cdp, plot, events, "four-panel price")
    for row in (1, 2, 3):
        box = subplot(page, plot, row)
        x = box["x"] + box["width"] * 0.45
        y = box["y"] + box["height"] * 0.5
        before = ranges(plot)
        touch(cdp, "touchStart", [(x, y)])
        touch(cdp, "touchMove", [(x + box["width"] * 0.12, y)])
        touch(cdp, "touchEnd")
        page.wait_for_timeout(220)
        assert ranges(plot)["x"] != before["x"]
        assert plot.evaluate(
            "p=>['xaxis2','xaxis3','xaxis4'].every(n=>JSON.stringify(p._fullLayout[n].range)===JSON.stringify(p._fullLayout.xaxis.range))"
        )
        assert plot.evaluate("p=>p._fullLayout.yaxis3.range[0]===0&&p._fullLayout.yaxis3.range[1]===100")
    plot.screenshot(path=f"/tmp/btc-osc-panels-{width}.png")
    for code, label, symbol in (
        ("ETH", "ETH", "ETHUSDT"),
        ("XRP", "XRP", "XRPUSDT"),
        ("NQ", "NQ", "NQ=F"),
        ("KOSPI", "코스피", "^KS11"),
        ("BTC", "BTC", "BTCUSDT"),
    ):
        select_market(page, label)
        page.wait_for_function(
            "s=>document.querySelector('#btc-chart-reader')?.dataset.symbol===s", arg=symbol
        )
        page.wait_for_function(
            "s=>{const plots=[...document.querySelectorAll('.js-plotly-plot')].filter(p=>p.getClientRects().length);return plots.length===1&&plots[0].layout?.meta?.btcLive?.symbol===s&&plots[0]._fullLayout.yaxis4&&plots[0].querySelectorAll('.nsewdrag').length===4;}",
            arg=symbol,
        )
    assert not errors, errors
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    widget.evaluate("clearInterval(window.__oscAlive)")
    cleanup(page, widget)
    context.close()
    return {
        "width": width,
        "seven_frames_four_panels": True,
        "live_rsi_macd_values": True,
        "single_plot_update_per_change": True,
        "duplicate_candle_no_draw": True,
        "all_panel_pan_and_price_pinch": True,
        "market_isolation": True,
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
