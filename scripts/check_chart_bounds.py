"""Touch/mouse chart boundaries: keep candles visible after zoom and repeated drags.

Use an instrumented development fixture server. No real exchange latency claim.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_chart_gestures import gesture_check, ranges, region_box, touch
from check_live_widget import select_market, MarketFixture, cleanup, install_quote_transport


def visible(plot):
    return plot.evaluate("""p=>{
      const axis=p._fullLayout.xaxis,r=axis.range.map(n=>axis.r2c(n)),y=p._fullLayout.yaxis.range;
      const read=a=>a?.bdata?new ({f8:Float64Array,f4:Float32Array}[a.dtype])(Uint8Array.from(atob(a.bdata),c=>c.charCodeAt(0)).buffer):a;
      const candle=p.data.find(t=>t.type==='candlestick');
      if(candle){const lo=read(candle.low),hi=read(candle.high),xs=candle.x.map(n=>axis.d2c(n));
        const indices=xs.map((x,i)=>[x,i]).filter(([x])=>r[0]<=x&&x<=r[1]).map(([,i])=>i);
        return {bars:indices.length,intersects:indices.some(i=>lo[i]<=y[1]&&hi[i]>=y[0])};}
      const points=p.data.filter(t=>t.x?.length&&t.y&&t.yaxis!=='y2'&&t.visible!==false&&t.visible!=='legendonly')
        .flatMap(t=>Array.from(read(t.y),(v,i)=>[axis.d2c(t.x[i]),v])).filter(([x,v])=>Number.isFinite(v)&&r[0]<=x&&x<=r[1]);
      return {bars:points.length,intersects:points.some(([,v])=>y[0]<=v&&v<=y[1])};
    }""")


def boundary_check(page, cdp, plot, event_log, label):
    # Existing checks cover price inspection, pinch anchoring and Auto toggling.
    gesture_check(page, cdp, plot, event_log, label)
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    d = box["width"] * 0.08
    touch(cdp, "touchStart", [(x - d, y), (x + d, y)])
    touch(cdp, "touchMove", [(x - d * 4, y), (x + d * 4, y)])
    touch(cdp, "touchEnd")
    page.wait_for_timeout(180)
    baseline = event_log.read_text() if event_log else None
    for step in range(8):
        box = region_box(page, plot)
        x, y = box["x"] + box["width"] * 0.88, box["y"] + box["height"] * 0.5
        touch(cdp, "touchStart", [(x, y)])
        for i in range(1, 9):
            touch(cdp, "touchMove", [(x - box["width"] * 0.76 * i / 8, y)])
            page.wait_for_timeout(10)
        touch(cdp, "touchEnd")
        page.wait_for_timeout(80)
        data = visible(plot)
        assert data["bars"] and data["intersects"], (label, "future pan", step, data, ranges(plot))
    # Even an extended manual vertical drag must leave some actual price data.
    reader = page.locator(
        "#btc-forecast-reader"
        if plot.evaluate("p=>p.layout.meta.btcLive.kind==='forecast'")
        else "#btc-chart-reader"
    )
    reader.get_by_role("button", name="오토", exact=True).tap()
    for direction in (1, -1):
        for _ in range(3):
            box = region_box(page, plot)
            x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * (0.15 if direction > 0 else 0.85)
            touch(cdp, "touchStart", [(x, y)])
            touch(cdp, "touchMove", [(x, y + direction * box["height"] * 0.7)])
            touch(cdp, "touchEnd")
            page.wait_for_timeout(100)
            assert visible(plot)["intersects"], (label, "manual Y", direction, ranges(plot))
    reader.get_by_role("button", name="오토", exact=True).tap()
    if baseline is not None:
        assert event_log.read_text() == baseline, (label, "gestures reran Python")
    return {"chart": label, "edge_pan": True, "manual_Y": True}


def mouse_live_check(page, crypto, event_log):
    select_market(page, "BTC")
    page.get_by_role("tab", name="시장 개요", exact=True).click()
    page.get_by_role("radio", name="5분", exact=True).click()
    page.wait_for_function(
        "()=>document.querySelector('#btc-chart-seed')?.dataset.symbol==='BTCUSDT'&&[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.symbol==='BTCUSDT'&&p.layout.meta.btcLive.timeframe==='5m')"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    box = region_box(page, plot)
    cdp = page.context.new_cdp_session(page)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    d = box["width"] * 0.08
    touch(cdp, "touchStart", [(x - d, y), (x + d, y)])
    touch(cdp, "touchMove", [(x - d * 4, y), (x + d * 4, y)])
    touch(cdp, "touchEnd")
    page.wait_for_timeout(180)
    baseline = event_log.read_text() if event_log else None

    def drag(direction):
        box = region_box(page, plot)
        x, y = box["x"] + box["width"] * (0.85 if direction < 0 else 0.15), box["y"] + box["height"] * 0.5
        page.mouse.move(x, y)
        page.mouse.down()
        for i in range(1, 9):
            page.mouse.move(x + direction * box["width"] * 0.7 * i / 8, y)
            page.wait_for_timeout(10)
        page.mouse.up()
        page.wait_for_timeout(100)
        data = visible(plot)
        assert data["bars"] and data["intersects"], ("mouse edge", data, ranges(plot))

    for _ in range(6):
        drag(-1)
    seed = page.locator("#btc-chart-seed").evaluate("e=>JSON.parse(e.dataset.seeds).frames['5m']")
    now = page.evaluate("Date.now()")
    assert seed["end"] <= now < seed["end"] + 300000, "Fixture crossed a candle boundary; restart it"
    price = seed["rows"][-1][4]
    packet = {
        "e": "kline",
        "E": now,
        "s": "BTCUSDT",
        "k": {
            "s": "BTCUSDT",
            "i": "5m",
            "t": seed["end"],
            "T": seed["end"] + 299999,
            "o": str(price),
            "c": str(price * 1.001),
            "h": str(price * 1.003),
            "l": str(price * 0.999),
            "v": "18",
            "x": False,
        },
    }

    def emit():
        crypto.evaluate(
            "p=>window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1).emit(JSON.stringify({data:p}))",
            packet,
        )
        page.wait_for_function(
            "v=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.dataset.liveEvent===String(v))",
            arg=packet["E"],
        )
        page.wait_for_timeout(150)
        assert plot.evaluate(
            "p=>p._fullLayout.xaxis.type==='date'&&p._fullLayout.xaxis2.type==='date'&&p.data.find(t=>t.type==='candlestick').x.every(Number.isFinite)"
        ), "Live update changed date axes or timestamp units"
        data = visible(plot)
        if not data["bars"] or not data["intersects"]:
            Path("/tmp/btc-pan-live-debug.json").write_text(
                json.dumps(
                    plot.evaluate(
                        """p=>({axis:p._fullLayout.xaxis.type,range:p._fullLayout.xaxis.range,layout:p.layout.xaxis,meta:p.layout.meta,traces:p.data.map(t=>({name:t.name,xType:typeof t.x,xStart:t.x?.slice?.(0,3),xEnd:t.x?.slice?.(-5),length:t.x?.length}))})"""
                    )
                )
            )
            page.screenshot(path="/tmp/btc-pan-live-debug.png")
        assert data["bars"] and data["intersects"], ("live edge", data, ranges(plot))

    emit()
    for _ in range(3):
        drag(1)
    past = ranges(plot)["x"]
    packet["E"] = page.evaluate("Date.now()")
    packet["k"]["c"] = str(price * 1.002)
    emit()
    assert ranges(plot)["x"] == past, "Live tick moved a past viewport"
    if baseline is not None:
        assert event_log.read_text() == baseline, "Mouse/live updates reran Python"
    return {"mouse_edge_pan": True, "live_candle_visible": True, "past_view_retained": True}


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.locator("#btc-chart-reader").wait_for(timeout=45000)
    crypto = next(f for f in page.frames if f.locator("#binance").count())
    crypto.evaluate("""window.__boundsHeartbeat=setInterval(()=>{
      const now=Date.now(),b=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);
      for(const [s,c] of [['BTCUSDT','100000'],['ETHUSDT','3000'],['SOLUSDT','150'],['XRPUSDT','1.1532']])b?.emit(JSON.stringify({data:{s,c,P:'2',E:now}}));
      window.__quoteSockets.find(s=>s.url.includes('api.upbit.com')&&s.readyState===1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:.01,timestamp:now}),true);
    },1000);""")
    cdp = context.new_cdp_session(page)
    results = []
    for asset, tf, name in (("BTC", "5m", "5분"), ("BTC", "1M", "월봉"), ("NQ", "5m", "5분")):
        page.get_by_role("radio", name=asset, exact=True).tap()
        page.get_by_role("tab", name="시장 개요", exact=True).tap()
        page.get_by_role("radio", name=name, exact=True).tap()
        page.wait_for_function(
            "v=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.timeframe===v.tf&&p.layout.meta.btcLive.symbol===v.s)",
            arg={"tf": tf, "s": "NQ=F" if asset == "NQ" else "BTCUSDT"},
        )
        plot = page.locator(".js-plotly-plot:visible").first
        results.append(boundary_check(page, cdp, plot, event_log, asset + " " + tf))
    page.get_by_role("tab", name="미래 예측", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.kind==='forecast')"
    )
    results.append(
        boundary_check(page, cdp, page.locator(".js-plotly-plot:visible").first, event_log, "NQ forecast")
    )
    if width == 1440:
        results.append(mouse_live_check(page, crypto, event_log))
    assert not errors, errors
    page.screenshot(path=f"/tmp/btc-bounds-{width}.png")
    crypto.evaluate("clearInterval(window.__boundsHeartbeat)")
    cleanup(page, crypto)
    context.close()
    return {"width": width, "results": results, "js_errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (390, 820, 1440):
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
