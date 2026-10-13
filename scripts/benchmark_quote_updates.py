"""Compare quote-card DOM mutations for 100 identical controlled BTC updates.

No network-latency claims: the real widget receives offline exchange packets.
Run with --before-widget pointing to an archived live_prices.py.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from benchmark_macro_updates import archived
from check_live_widget import MarketFixture, cleanup, install_quote_transport, send, widget_html


def measure(browser, source, width):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    page.clock.install()
    install_quote_transport(page)
    MarketFixture(page)
    page.route("http://widget.test/", lambda r: r.fulfill(body=source, content_type="text/html"))
    page.goto("http://widget.test/")
    page.locator('#premium[data-ready="true"]').wait_for()
    page.clock.run_for(200)
    page.evaluate("""()=>{
      window.__writes={total:0,ethereum:0,forex:0};
      new MutationObserver(records=>{
        for (const r of records) {
          const node=r.target.nodeType===1 ? r.target : r.target.parentElement;
          const card=node.closest('.market');
          // Canvas data-samples is a diagnostic; measure user-visible text,
          // status, colors and card attributes only.
          if (!card || node.tagName==='CANVAS') continue;
          window.__writes.total++;
          if (card.id in window.__writes) window.__writes[card.id]++;
        }
      }).observe(document.querySelector('.dashboard'),
        {childList:true,characterData:true,attributes:true,subtree:true});
    }""")
    for tick in range(100):
        send(page.main_frame, "BTCUSDT", 100000 + tick, page.evaluate("Date.now()"))
        page.clock.run_for(100)
    result = page.evaluate("window.__writes")
    assert page.locator("#binance .price span").inner_text() == "100,099.00"
    cleanup(page, page.main_frame)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-widget", type=Path, required=True)
    args = parser.parse_args()
    # Old source has a bridge placeholder. In this isolated card benchmark no
    # parent analysis exists, but the complete bridge must still be present.
    current = widget_html()
    before = archived(args.before_widget)
    if "/* LIVE_ANALYSIS_BRIDGE */" in before:
        import ast

        module = ast.parse(Path("src/btc_analyzer/ui/live_analysis.py").read_text())
        bridge = next(
            ast.literal_eval(n.value)
            for n in module.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "LIVE_ANALYSIS_JS" for t in n.targets)
        )
        before = before.replace("/* LIVE_ANALYSIS_BRIDGE */", bridge)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        results = []
        for width in (390, 1440):
            old, new = measure(browser, before, width), measure(browser, current, width)
            assert new["total"] < old["total"] / 2, (old, new)
            results.append({"width": width, "before": old, "after": new})
        browser.close()
    print(json.dumps(results))


if __name__ == "__main__":
    main()
