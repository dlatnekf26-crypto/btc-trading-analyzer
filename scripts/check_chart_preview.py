"""Verify actual candle movement without relayout, final axes and touch cleanup."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_chart_gestures import ranges, region_box, touch
from check_chart_bounds import visible
from check_live_widget import MarketFixture, cleanup, install_quote_transport


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
    box = region_box(page, plot)
    candle = plot.evaluate_handle(
        """p=>{const r=p.querySelector('.nsewdrag').getBoundingClientRect();return [...p.querySelectorAll('.boxlayer path.box')].find(n=>{const b=n.getBoundingClientRect();return b.x>r.x+r.width*.25&&b.right<r.x+r.width*.75;});}"""
    ).as_element()
    assert candle
    original = ranges(plot)
    bbox = candle.bounding_box()
    baseline = event_log.read_text() if event_log else None
    cdp = context.new_cdp_session(page)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    distance = box["width"] * 0.12
    touch(cdp, "touchStart", [(x, y)])
    touch(cdp, "touchMove", [(x + distance, y)])
    page.wait_for_timeout(70)
    assert plot.get_attribute("data-gesture-preview") == "true"
    assert ranges(plot) == original, "Dragging recalculated full axes"
    moved = candle.bounding_box()
    assert abs(moved["x"] - bbox["x"] - distance) < 2, (bbox, moved, distance)
    page.screenshot(path=f"/tmp/btc-smooth-preview-{width}.png")
    touch(cdp, "touchEnd")
    page.wait_for_timeout(200)
    assert ranges(plot)["x"] != original["x"]
    assert visible(plot)["bars"] and visible(plot)["intersects"]
    assert not plot.get_attribute("data-gesture-preview")
    assert plot.evaluate("p=>[...p.querySelectorAll('.overplot .mlayer')].every(n=>!n.style.transform)")
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
