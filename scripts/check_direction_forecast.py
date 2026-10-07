"""Three-direction forecasts, mobile hover and preserved model/stream behavior.

Feed fixtures exercise the application; they do not demonstrate forecast accuracy.
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport
from check_touch_charts import inspect


def traces(plot):
    return plot.evaluate("p=>p.data.map(t=>({name:t.name,x:t.x,y:t.y,meta:t.meta,line:t.line}))")


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.get_by_role("tab", name="미래 예측", exact=True).tap(timeout=45000)
    page.locator(".btc-direction-card").first.wait_for(timeout=30000)
    plot = page.locator(".js-plotly-plot:visible").first
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.filter(t=>t.meta?.direction).length===3)"
    )
    crypto = next(frame for frame in page.frames if frame.locator("#binance").count())
    sockets = crypto.evaluate("window.__quoteSockets.length")
    assert (
        page.locator(".btc-direction-card").count() == 3
        and page.locator(".js-plotly-plot:visible").count() == 1
    )
    assert "가중 비중" in page.locator(".btc-direction-cards").inner_text()
    for horizon, label in (("1w", "1주"), ("1mo", "1개월"), ("3mo", "3개월"), ("6mo", "6개월")):
        page.get_by_role("radio", name=label, exact=True).tap()
        origin = pd.Timestamp.now(tz="UTC").normalize()
        target = origin + (
            pd.Timedelta(days=7)
            if horizon == "1w"
            else pd.DateOffset(months={"1mo": 1, "3mo": 3, "6mo": 6}[horizon])
        )
        length = (target - origin).days + 1
        page.wait_for_function(
            "n=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.filter(t=>t.meta?.direction).length===3 && p.data[3].x.length===n)",
            arg=length,
        )
        data = traces(plot)
        for trace in data[3:]:
            assert len(trace["y"]) == length and trace["x"][-1].startswith(target.strftime("%Y-%m-%d"))
            assert trace["y"][0] == data[3]["y"][0]
        assert all(trace["line"]["width"] == 3.5 for trace in data[3:] if "우세" in trace["name"])
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    cdp = context.new_cdp_session(page)
    baseline = event_log.read_text() if event_log else None
    inspect(page, cdp, plot, event_log, "direction comparison")
    page.evaluate(
        "document.querySelector('.btc-direction-cards').scrollIntoView({block:'center',behavior:'instant'})"
    )
    page.locator(".btc-direction-cards").screenshot(path=f"/tmp/btc-direction-cards-{width}.png")
    plot.screenshot(path=f"/tmp/btc-direction-chart-{width}.png")
    base = traces(plot)
    page.get_by_text("예상 변동 범위 함께 보기", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.[0]?.visible===false)"
    )
    assert traces(plot) == base
    page.get_by_text("예상 변동 범위 함께 보기", exact=True).tap()
    page.get_by_role("radio", name="모델·과거 경로", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.[4]?.name==='과거 사례 재현')"
    )
    model = traces(plot)
    page.get_by_role("radio", name="2위", exact=True).tap()
    page.wait_for_function(
        "old=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.[4]?.name==='과거 사례 재현' && JSON.stringify(p.data[4].y)!==old)",
        arg=json.dumps(model[4]["y"], separators=(",", ":")),
    )
    assert traces(plot)[:4] == model[:4]
    page.get_by_role("radio", name="세 방향 비교", exact=True).tap()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.filter(t=>t.meta?.direction).length===3)"
    )
    assert traces(plot) == base
    page.get_by_text("뉴스 영향 함께 반영", exact=True).tap()
    page.wait_for_function("()=>!document.querySelector('.btc-news-scenario')")
    branch_prices = json.dumps([trace["y"] for trace in base[3:]], separators=(",", ":"))
    page.wait_for_function(
        "old=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && p.data?.filter(t=>t.meta?.direction).length===3 && JSON.stringify(p.data.filter(t=>t.meta?.direction).map(t=>t.y))!==old)",
        arg=branch_prices,
    )
    assert len(traces(plot)) == 6
    page.get_by_text("뉴스 영향 함께 반영", exact=True).tap()
    page.locator(".btc-news-scenario").wait_for()
    page.wait_for_function(
        "expected=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.offsetParent!==null && JSON.stringify(p.data?.filter(t=>t.meta?.direction).map(t=>t.y))===expected)",
        arg=branch_prices,
    )
    assert traces(plot) == base
    if baseline is not None:
        assert event_log.read_text() == baseline, "Direction controls re-entered parent analysis"
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    assert not page.locator('[data-testid="stException"]').count()
    cleanup(page, page.main_frame)
    context.close()
    return {
        "width": width,
        "four_horizons": "passed",
        "three_directions": "passed",
        "model_and_news_preserved": "passed",
        "touch_scroll": "passed",
        "parent_analysis_checked": baseline is not None,
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
