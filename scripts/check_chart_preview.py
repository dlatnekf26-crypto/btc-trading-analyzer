"""Verify actual candle movement without relayout, final axes and touch cleanup."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_chart_gestures import ranges, region_box, touch
from check_chart_bounds import visible
from check_live_widget import MarketFixture, cleanup, install_quote_transport


def canvas_point(plot):
    return plot.evaluate("""p=>{
      const read=a=>a?.bdata?Array.from(new Float64Array(Uint8Array.from(atob(a.bdata),c=>c.charCodeAt(0)).buffer)):a;
      const t=p.data.find(t=>t.type==='candlestick'),x=p._fullLayout.xaxis,y=p._fullLayout.yaxis;
      const c=p.querySelector('.btc-canvas-layer canvas[data-pane=xy]'),ctx=c.getContext('2d'),ratio=c.width/x._length;
      const o=read(t.open),close=read(t.close);
      for(let i=0;i<t.x.length;i++){
        const px=x.d2p(t.x[i]),py=(y.c2p(o[i])+y.c2p(close[i]))/2;
        if(px<x._length*.25||px>x._length*.6||py<4||py>y._length-4)continue;
        const color=close[i]>=o[i]?[239,63,80]:[37,99,235],d=ctx.getImageData(Math.round(px*ratio),Math.round(py*ratio),1,1).data;
        if(d[3]>80&&color.every((n,j)=>Math.abs(n-d[j])<12))return {x:px,y:py,color};
      }
      return null;
    }""")


def canvas_ink(plot, point, offset):
    assert point, "No source candle pixel found"
    return plot.evaluate(
        """(p,{point,offset})=>{
      const c=p.querySelector('.btc-canvas-layer canvas[data-pane=xy]'),ratio=c.width/p._fullLayout.xaxis._length;
      const d=c.getContext('2d').getImageData(Math.round((point.x+offset)*ratio)-1,Math.round(point.y*ratio)-1,3,3).data;
      return Array.from({length:9},(_,j)=>j*4).some(k=>d[k+3]>80&&point.color.every((n,j)=>Math.abs(n-d[k+j])<12));
    }""",
        {"point": point, "offset": offset},
    )


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
    page.get_by_role("radio", name="5분", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.timeframe==='5m'&&p.querySelector('.nsewdrag')?.getBoundingClientRect().width>0)"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    page.wait_for_function(
        "()=>{const p=document.querySelector('.js-plotly-plot');return !p.layout.meta.btcLive.canvasTraces||p.dataset.canvasRevision===p.layout.uirevision;}"
    )
    canvas = plot.get_attribute("data-canvas-rendering") == "ready"
    auto = page.locator("#btc-chart-reader").get_by_role("button", name="오토", exact=True)
    if canvas:
        auto.tap()  # Fix the vertical scale while checking horizontal pixel travel.
    box = region_box(page, plot)
    candle = (
        None
        if canvas
        else plot.evaluate_handle(
            """p=>{const r=p.querySelector('.nsewdrag').getBoundingClientRect();return [...p.querySelectorAll('.boxlayer path.box')].find(n=>{const b=n.getBoundingClientRect();return b.x>r.x+r.width*.25&&b.right<r.x+r.width*.75;});}"""
        ).as_element()
    )
    assert canvas or candle
    original = ranges(plot)
    point = canvas_point(plot) if canvas else None
    bbox = None if canvas else candle.bounding_box()
    baseline = event_log.read_text() if event_log else None
    cdp = context.new_cdp_session(page)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    distance = box["width"] * 0.12
    touch(cdp, "touchStart", [(x, y)])
    touch(cdp, "touchMove", [(x + distance, y)])
    page.wait_for_timeout(70)
    assert plot.get_attribute("data-gesture-preview") == "true"
    assert ranges(plot) == original, "Dragging recalculated full axes"
    if canvas:
        assert canvas_ink(plot, point, distance), "Canvas candle did not follow the finger"
    else:
        moved = candle.bounding_box()
        assert abs(moved["x"] - bbox["x"] - distance) < 2, (bbox, moved, distance)
    page.screenshot(path=f"/tmp/btc-smooth-preview-{width}.png")
    touch(cdp, "touchEnd")
    page.wait_for_timeout(200)
    assert ranges(plot)["x"] != original["x"]
    assert visible(plot)["bars"] and visible(plot)["intersects"]
    assert not plot.get_attribute("data-gesture-preview")
    assert plot.evaluate("p=>[...p.querySelectorAll('.overplot .mlayer')].every(n=>!n.style.transform)")
    if canvas:
        auto.tap()
    # Cancellation rolls back the temporary drawing rather than replaying it.
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    before = ranges(plot)
    touch(cdp, "touchStart", [(x, y)])
    touch(cdp, "touchMove", [(x + distance, y)])
    page.wait_for_timeout(70)
    touch(cdp, "touchCancel")
    page.wait_for_timeout(60)
    assert ranges(plot) == before and not plot.get_attribute("data-gesture-preview")
    # One -> two -> one fingers keeps the same uncommitted view until release.
    touch(cdp, "touchStart", [(x, y)])
    touch(cdp, "touchMove", [(x + 20, y)])
    page.wait_for_timeout(50)
    touch(cdp, "touchStart", [(x + 20, y), (x + 60, y)])
    touch(cdp, "touchMove", [(x + 10, y), (x + 70, y)])
    page.wait_for_timeout(50)
    touch(cdp, "touchEnd", [(x + 10, y)])
    touch(cdp, "touchMove", [(x + 25, y)])
    page.wait_for_timeout(50)
    assert ranges(plot) == before
    touch(cdp, "touchEnd")
    page.wait_for_timeout(200)
    after = ranges(plot)
    assert abs((after["x"][1] - after["x"][0]) / (before["x"][1] - before["x"][0]) - 1 / 1.5) < 0.01
    assert visible(plot)["bars"] and not plot.get_attribute("data-gesture-preview")
    if canvas:
        # A native refresh can replace arrays for the same market while dragging.
        # It must keep accepting moves, then commit the last visible position.
        box = region_box(page, plot)
        x, y = box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.5
        before = ranges(plot)
        touch(cdp, "touchStart", [(x, y)])
        touch(cdp, "touchMove", [(x + 20, y)])
        page.wait_for_timeout(50)
        plot.evaluate("p=>Plotly.react(p,p.data.map(t=>({...t})),p.layout,p._context)")
        touch(cdp, "touchMove", [(x + 50, y)])
        page.wait_for_timeout(60)
        assert plot.get_attribute("data-gesture-preview") == "true"
        touch(cdp, "touchEnd")
        page.wait_for_function("()=>!document.querySelector('.js-plotly-plot')?.dataset.gesturePreview")
        assert ranges(plot)["x"] != before["x"]
        assert canvas_point(plot)
    if baseline is not None:
        assert event_log.read_text() == baseline, "Local preview reran Python"
    assert not errors, errors
    cleanup(page, next(f for f in page.frames if f.locator("#binance").count()))
    context.close()
    return {
        "width": width,
        "candle_tracks_finger": True,
        "no_relayout_during_drag": True,
        "cancel_cleanup": True,
        "one_two_one_fingers": True,
        "same_market_refresh_keeps_dragging": canvas,
        "js_errors": errors,
    }


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
