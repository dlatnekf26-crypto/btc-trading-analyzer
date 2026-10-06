"""Count redundant native macro DOM writes under identical controlled crypto ticks.

The two common NQ/10-year cards allow comparison with an archived widget.
This measures DOM work, not exchange latency, CPU time or hosted page loading.
"""

import argparse
import ast
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, send, send_macro, widget_html
from check_macro_stream import SEED


def archived(path):
    module = ast.parse(path.read_text())
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LIVE_PRICES_HTML" for target in node.targets)
    )


def measure(browser, source, width):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    page.clock.install()
    install_quote_transport(page)
    MarketFixture(page)
    page.route(
        "http://widget.test/",
        lambda route: route.fulfill(
            body=source.replace('<div class="dashboard">', SEED + '<div class="dashboard">'),
            content_type="text/html",
        ),
    )
    page.goto("http://widget.test/")
    page.locator("#ethereum .price span").get_by_text("3,000.25", exact=True).wait_for()
    now = page.evaluate("Date.now()")
    for symbol, price in (("NQ=F", 22600.5), ("CL=F", 88.5), ("^TNX", 4.5), ("^TYX", 4.9)):
        send_macro(page.main_frame, symbol, price, now - 1000)
    page.clock.run_for(100)
    page.evaluate("""()=>{
      window.__macroWrites={common:0,all:0};
      const watcher=new MutationObserver(records=>{
        for (const record of records) {
          const node=record.target.nodeType===1 ? record.target : record.target.parentElement;
          const card=node.closest('.btc-macro-card');
          if (card) {window.__macroWrites.all++;if(['macro-nq','macro-tnx'].includes(card.id))window.__macroWrites.common++;}
        }
      });watcher.observe(document.querySelector('.btc-macro-grid'),{childList:true,characterData:true,subtree:true});
    }""")
    for tick in range(100):
        now = page.evaluate("Date.now()")
        send(page.main_frame, "BTCUSDT", 100000 + tick, now)
        send(page.main_frame, "ETHUSDT", 3000 + tick / 100, now)
        page.clock.run_for(100)
    counts = page.evaluate("window.__macroWrites")
    cleanup(page, page.main_frame)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-widget", type=Path, required=True)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        results = []
        for width in (390, 1440):
            before = measure(browser, archived(args.before_widget), width)
            after = measure(browser, widget_html(), width)
            assert after["common"] < before["common"] / 2, (before, after)
            results.append(
                {
                    "width": width,
                    "ticks_per_asset": 100,
                    "before_two_card_writes": before["common"],
                    "after_two_card_writes": after["common"],
                    "after_all_four_card_writes": after["all"],
                    "common_card_reduction": round(1 - after["common"] / before["common"], 4),
                }
            )
        print(json.dumps(results))
        browser.close()
