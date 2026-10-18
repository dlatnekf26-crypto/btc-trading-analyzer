"""Real browser touch inputs: inspect free prices, pan charts, scroll and tap.

Use a developer-injected Live app for deterministic data. This is Chromium device
emulation, not proof for every physical phone or Safari version.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def ranges(plot):
    return plot.evaluate(
        "e=>Object.fromEntries(Object.entries(e._fullLayout).filter(([k,v])=>/^[xy]axis\\d*$/.test(k)).map(([k,v])=>[k,v.range]))"
    )


def touch(cdp, kind, points=()):
    cdp.send(
        "Input.dispatchTouchEvent",
        {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i + 1} for i, (x, y) in enumerate(points)]},
    )


def inspect(page, cdp, plot, event_log, label, subplot=0):
    region = plot.locator(".nsewdrag").nth(subplot)
    region.scroll_into_view_if_needed()
    page.wait_for_timeout(200)  # Wait for Plotly/Streamlit layout transitions before device coordinates.
    rect = region.bounding_box()
    assert rect and rect["width"] > 100
    # Stay in the visible graph region even when the taller indicator chart
    # extends beyond the device viewport.
    x = rect["x"] + rect["width"] * 0.25
    y = max(80, min(page.viewport_size["height"] - 80, rect["y"] + rect["height"] * 0.5))
    assert rect["y"] < y < rect["y"] + rect["height"]
    original = ranges(plot)
    baseline = event_log.read_text() if event_log else None
    touch(cdp, "touchStart", [(x, y)])
    page.wait_for_timeout(400)
    crosshair = plot.locator(".btc-crosshair:visible")
    tooltip = crosshair if crosshair.count() else plot.locator(".hoverlayer")
    before = tooltip.text_content()
    assert before and any(char.isdigit() for char in before), f"{label}: price missing while finger is down"
    for step in range(1, 6):
        touch(cdp, "touchMove", [(x + rect["width"] * 0.08 * step, y)])
        page.wait_for_timeout(40)
    after = tooltip.text_content()
    assert after and before != after, f"{label}: tooltip did not follow the finger"
    touch(cdp, "touchEnd")
    assert ranges(plot) == original, (label, original, ranges(plot))
    # Pinch is exercised by check_chart_gestures; inspection alone keeps the axes.
    scroller = (
        page.get_by_role("dialog")
        if page.get_by_role("dialog").count()
        else page.locator('[data-testid="stMain"]')
    )
    before_scroll = scroller.evaluate("e=>e.scrollTop")
    remaining = scroller.evaluate("e=>e.scrollHeight-e.clientHeight-e.scrollTop")
    # A short comparison page may already be at its bottom. Swipe toward the
    # available scroll space instead of mistaking a page boundary for a trap.
    direction = -1 if remaining >= before_scroll else 1
    distance = min(120, y - 30 if direction < 0 else page.viewport_size["height"] - y - 30)
    assert distance > 40
    touch(cdp, "touchStart", [(x, y)])
    for step in range(1, 6):
        touch(cdp, "touchMove", [(x, y + direction * distance * step / 5)])
        page.wait_for_timeout(30)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(200)
    assert (scroller.evaluate("e=>e.scrollTop") - before_scroll) * -direction > 20, (
        f"{label}: chart trapped vertical scrolling"
    )
    assert ranges(plot) == original, (label, original, ranges(plot))
    if baseline is not None:
        assert event_log.read_text() == baseline, f"{label}: hovering reran Python analysis"
    assert not page.locator('[data-testid="stException"]').count()


def verify(browser, width, url, event_log):
    from check_chart_gestures import verify as current_verify

    return current_verify(browser, width, url, event_log)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (390, 820, 1440):
            try:
                print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
            except Exception:
                for context in browser.contexts:
                    for page in context.pages:
                        page.screenshot(path=f"/tmp/btc-touch-failure-{width}.png")
                        Path(f"/tmp/btc-touch-failure-{width}.txt").write_text(
                            page.locator("body").inner_text()
                        )
                raise
        browser.close()
