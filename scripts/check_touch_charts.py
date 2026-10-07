"""Real browser touch inputs: inspect prices, preserve chart ranges, scroll and tap.

Use a developer-injected Live app for deterministic data. This is Chromium device
emulation, not proof for every physical phone or Safari version.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport


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
    page.wait_for_timeout(100)
    before = plot.locator(".hoverlayer").text_content()
    assert before and any(char.isdigit() for char in before), f"{label}: price missing while finger is down"
    for step in range(1, 6):
        touch(cdp, "touchMove", [(x + rect["width"] * 0.08 * step, y)])
        page.wait_for_timeout(40)
    after = plot.locator(".hoverlayer").text_content()
    assert after and before != after, f"{label}: tooltip did not follow the finger"
    touch(cdp, "touchEnd")
    assert ranges(plot) == original
    # Double tapping cannot reset/zoom the axes.
    for _ in range(2):
        touch(cdp, "touchStart", [(x, y)])
        touch(cdp, "touchEnd")
        page.wait_for_timeout(80)
    # Two fingers do not create a zoom box or a pinch-scaled chart.
    touch(cdp, "touchStart", [(x, y), (x + 40, y + 30)])
    touch(cdp, "touchMove", [(x - 15, y - 15), (x + 70, y + 45)])
    touch(cdp, "touchEnd")
    assert ranges(plot) == original
    scroller = page.locator('[data-testid="stMain"]')
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
    assert ranges(plot) == original
    if baseline is not None:
        assert event_log.read_text() == baseline, f"{label}: hovering reran Python analysis"
    assert not page.locator('[data-testid="stException"]').count()


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.get_by_role("tab", name="시장 개요", exact=True).wait_for(timeout=45000)
    cdp = context.new_cdp_session(page)
    if width == 1440:
        plot = page.locator(".js-plotly-plot:visible").first
        plot.scroll_into_view_if_needed()
        rect = plot.locator(".nsewdrag").first.bounding_box()
        page.mouse.move(rect["x"] + rect["width"] * 0.4, rect["y"] + rect["height"] * 0.5)
        page.wait_for_timeout(150)
        assert any(char.isdigit() for char in plot.locator(".hoverlayer").text_content())
    inspect(page, cdp, page.locator(".js-plotly-plot:visible").first, event_log, "market")
    # A control still receives a touch after swiping on the chart.
    page.get_by_role("radio", name="상세", exact=True).tap()
    page.get_by_text("표시할 봉 수", exact=True).wait_for()
    inspect(page, cdp, page.locator(".js-plotly-plot:visible").first, event_log, "detailed market")
    page.get_by_role("tab", name="미래 예측", exact=True).tap()
    page.get_by_text("기간별 가격 전망", exact=True).wait_for()
    plot = page.locator(".js-plotly-plot:visible").first
    plot.wait_for()
    inspect(page, cdp, plot, event_log, "forecast")
    page.screenshot(path=f"/tmp/btc-touch-forecast-{width}.png")
    page.get_by_role("radio", name="과거 비교", exact=True).tap()
    page.get_by_text("비슷했던 시기", exact=True).wait_for()
    plot = page.locator(".js-plotly-plot:visible").first
    for subplot in range(plot.locator(".nsewdrag").count()):
        inspect(page, cdp, plot, event_log, f"comparison {subplot + 1}", subplot)
    page.get_by_role("tab", name="기술 지표", exact=True).tap()
    page.get_by_text("기술지표 한눈에 보기", exact=True).wait_for()
    assert page.locator(".btc-indicator-card:visible").count() == 6
    for label in ("매수·매도 힘", "추세 탄력", "변동 폭", "밴드 폭", "거래량"):
        baseline = event_log.read_text() if event_log else None
        page.get_by_role("radio", name=label, exact=True).tap()
        expected = {
            "매수·매도 힘": "매수·매도 힘",
            "추세 탄력": "MACD",
            "변동 폭": "평균 변동 폭",
            "밴드 폭": "볼린저밴드 폭",
            "거래량": "평균 대비 거래량",
        }[label]
        page.wait_for_function(
            "name=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p._fullData?.some(t=>t.name===name))",
            arg=expected,
        )
        plot = page.locator(".js-plotly-plot:visible").first
        page.get_by_text("최근 120개 확정 봉", exact=False).wait_for()
        inspect(page, cdp, plot, event_log, f"indicators {label}")
        if baseline is not None:
            assert event_log.read_text() == baseline, "Indicator selection reran parent analysis"
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=f"/tmp/btc-touch-indicators-{width}.png", full_page=True)
    page.get_by_role("radio", name="월봉", exact=True).tap()
    page.get_by_text("월봉 · 확정 봉 마감", exact=False).wait_for()
    assert page.locator(".btc-indicator-card:visible").count() == 6
    page.get_by_role("radio", name="일봉", exact=True).tap()
    page.get_by_text("일봉 · 확정 봉 마감", exact=False).wait_for()
    page.get_by_role("tab", name="미래 예측", exact=True).tap()
    # Target the actual button so Playwright waits for enabled state after the
    # tab rerun; tapping a text child can be dropped while its button is disabled.
    page.get_by_role("radio", name="예측 경로", exact=True).tap()
    page.get_by_role("radio", name="모델·과거 경로", exact=True).tap()
    page.get_by_text("함께 볼 과거 경로 · 유사도 순", exact=True).wait_for()
    page.get_by_role("radio", name="2위", exact=True).tap()
    page.get_by_text("당시에는", exact=False).first.wait_for()
    removed = ("과거 예측 성적", "세부 유사도", "CSV", "다운로드")
    labels = page.locator(
        '[data-testid="stExpander"] summary, [data-testid="stDownloadButton"]'
    ).all_text_contents()
    assert not any(term in label for label in labels for term in removed)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not page.locator('[data-testid="stException"]').count()
    cleanup(page, page.main_frame)
    context.close()
    return {
        "width": width,
        "touch_hover": "passed",
        "follow_finger": "passed",
        "zoom_disabled": "passed",
        "page_scroll": "passed",
        "controls_after_swipe": "passed",
        "removed_footers": "passed",
        "parent_analysis_checked": event_log is not None,
    }


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
