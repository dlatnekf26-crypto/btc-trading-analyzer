"""Native forecast case switching preserves the model and skips parent analysis.

Use against a running Live dashboard (or developer-injected public fixtures). An instrumentation log
may be passed to verify that child controls never re-enter parent analysis.
"""

import argparse
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport


def verify(browser, width, url, event_log):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.get_by_role("tab", name="시장 개요", exact=True).wait_for(timeout=45000)
    page.get_by_role("tab", name="미래 예측", exact=True).click()
    page.get_by_text("기간별 가격 전망", exact=True).wait_for()
    page.get_by_text("3개월", exact=True).click()
    page.get_by_text(re.compile("예측 도착일 ")).wait_for()
    panel = page.get_by_role("tabpanel", name="미래 예측", exact=True)
    plot = panel.locator(".js-plotly-plot")
    plot.wait_for()
    page.wait_for_function(
        "() => [...document.querySelectorAll('.js-plotly-plot')].some(el=>el.getBoundingClientRect().width>0 && el.data?.length>=5 && el.data[3].x.length>=90)"
    )
    before = plot.evaluate("el=>el.data.map(t=>({name:t.name,y:t.y,x:t.x}))")
    assert before[4]["name"] == "과거 사례 재현"
    baseline = event_log.read_text() if event_log and event_log.exists() else None
    page.get_by_text("2위", exact=True).click()
    page.wait_for_function(
        """(before)=>{const el=[...document.querySelectorAll('.js-plotly-plot')].find(e=>e.getBoundingClientRect().width>0 && e.data?.[4]?.name==='과거 사례 재현');return el?.data?.length>=5 && JSON.stringify(el.data[4].y)!==before}""",
        arg=json.dumps(before[4]["y"], separators=(",", ":")),
    )
    after = plot.evaluate("el=>el.data.map(t=>({name:t.name,y:t.y,x:t.x}))")
    assert before[:4] == after[:4], "Picking an analogue altered the prediction or its uncertainty"
    assert before[4]["y"] != after[4]["y"]
    if baseline is not None:
        assert event_log.read_text() == baseline, "Case selection recalculated parent analysis"
    plot.scroll_into_view_if_needed()
    page.screenshot(path=f"/tmp/btc-replay-{width}.png")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not page.locator('[data-testid="stException"]').count()
    cleanup(page, page.main_frame)
    return {"width": width, "case_switch": "passed", "parent_analysis_checked": baseline is not None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        print(json.dumps([verify(browser, w, args.app_url, args.event_log) for w in (1440, 390)]))
        browser.close()
