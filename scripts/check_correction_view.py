"""Release consensus, conditional chart paths and mobile interaction with fixtures."""

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport
from check_touch_charts import inspect


def traces(plot):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = plot.evaluate(
            "p=>p.data?.length ? p.data.filter(t=>!t.name.startsWith('실시간')).map(t=>({name:t.name,x:t.x,y:t.y})) : null"
        )
        if value is not None:
            return value
        plot.page.wait_for_timeout(50)
    raise AssertionError("Updated forecast chart did not finish drawing")


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    install_quote_transport(page)
    fixture = MarketFixture(page)
    page.goto(url)
    # Complete the initial market render before requesting a different tab.
    page.locator(".btc-pattern-card").wait_for(timeout=45000)
    page.wait_for_function("()=>document.querySelector('.js-plotly-plot')?.data?.length > 0")
    page.get_by_role("tab", name="미래 예측", exact=True).tap(timeout=45000)
    page.locator(".btc-release-card").wait_for(timeout=25000)
    page.get_by_role("radio", name="예상 부합", exact=True).wait_for()
    assert "0.3%" in page.locator(".btc-release-card").inner_text()
    assert "0.2%" in page.locator(".btc-release-card").inner_text()
    assert page.locator(".btc-correction-cards article").count() == 3
    assert page.get_by_text("현재 지표", exact=False).count()
    page.get_by_role("radio", name="모델·과거 경로", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.some(t=>t.name==='뉴스 반영 시나리오'))"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    plot.wait_for()
    base = traces(plot)
    original_shapes = plot.evaluate("p=>p.layout.shapes")
    assert any(shape.get("line", {}).get("color") == "#936624" for shape in original_shapes)
    crypto = next(frame for frame in page.frames if frame.locator("#binance").count())
    crypto.locator("#binance.fresh").wait_for()
    fixture.rest = False  # Price ticks have their own live/hold regression driver.
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.dataset.liveEvent)"
    )
    sockets = crypto.evaluate("window.__quoteSockets.length")
    baseline = event_log.read_text() if event_log else None
    page.get_by_role("radio", name="코인에 부담", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.data?.some(t=>t.name==='발표 조건부 경로'))"
    )
    adverse = traces(plot)
    assert adverse[:-1] == base
    original_center = next(trace for trace in base if trace["name"] == "뉴스 반영 시나리오")
    assert adverse[-1]["y"][0] == original_center["y"][0]
    assert min(a - b for a, b in zip(adverse[-1]["y"], original_center["y"])) < 0
    # This driver verifies the unchanged closed-model geometry. The separate
    # live driver tests real ticks/hold/hover; their legitimate axis changes
    # must not be mistaken here for a user's forbidden zoom gesture.
    plot.evaluate(
        "async p=>{const indices=p.layout.meta?.btcLive?.liveIndices;if(indices)await Plotly.restyle(p,{visible:false},indices);}"
    )
    cdp = context.new_cdp_session(page)
    inspect(page, cdp, plot, event_log, "release what-if")
    page.screenshot(path=f"/tmp/btc-correction-chart-{width}.png")
    page.get_by_role("radio", name="코인에 우호", exact=True).tap()
    page.wait_for_function(
        "old=>{const p=[...document.querySelectorAll('.js-plotly-plot')].find(p=>p.offsetParent!==null),t=p?.data?.find(t=>t.name==='발표 조건부 경로');return t && JSON.stringify(t.y)!==old}",
        arg=json.dumps(adverse[-1]["y"], separators=(",", ":")),
    )
    favorable = traces(plot)
    assert favorable[:-1] == base
    assert max(a - b for a, b in zip(favorable[-1]["y"], original_center["y"])) > 0
    page.get_by_role("radio", name="예상 부합", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data && !p.data.some(t=>t.name==='발표 조건부 경로'))"
    )
    assert traces(plot) == base
    page.get_by_role("radio", name="−10%", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('.btc-correction-cards')?.innerText.includes('조정')")
    assert traces(plot) == base
    if baseline is not None:
        assert event_log.read_text() == baseline, "Correction controls re-entered parent analysis"
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not page.locator('[data-testid="stException"]').count()
    page.locator(".btc-release-card").screenshot(path=f"/tmp/btc-correction-release-{width}.png")
    page.locator(".btc-correction-cards").screenshot(path=f"/tmp/btc-correction-summary-{width}.png")
    cleanup(page, page.main_frame)
    context.close()
    return {
        "width": width,
        "consensus_and_prior": "passed",
        "conditional_only": "passed",
        "touch_and_scroll": "passed",
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
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
