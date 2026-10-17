"""Actual installability/offline navigation and candle inspection in Chromium.

Exchange fixtures control prices; this does not measure exchange latency or Safari.
"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport
from check_touch_charts import touch, ranges


def installability(playwright, url):
    with TemporaryDirectory(prefix="btc-pwa-profile-") as profile:
        context = playwright.chromium.launch_persistent_context(
            profile, executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        page = context.pages[0]
        install_quote_transport(page)
        MarketFixture(page)
        page.goto(url)
        page.locator("#btc-chart-reader").wait_for(timeout=45000)
        page.wait_for_function("()=>navigator.serviceWorker.controller!==null")
        page.locator("#btc-pwa-install").wait_for()
        cdp = context.new_cdp_session(page)
        cdp.send("Page.enable")
        data = cdp.send("Page.getAppManifest")
        assert not data["errors"], data
        manifest = json.loads(data["data"])
        assert manifest["display"] == "standalone" and manifest["scope"] == "/"
        errors = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
        assert not errors, errors
        keys = page.evaluate(
            "caches.open('crypto-signal-shell-v1').then(c=>c.keys()).then(rs=>rs.map(r=>new URL(r.url).pathname).sort())"
        )
        assert keys == ["/app-assets/icon-192.png", "/app-assets/icon-512.png", "/app-assets/offline.html"], (
            keys
        )
        context.set_offline(True)
        page.reload(wait_until="domcontentloaded")
        assert page.title() == "연결 대기 · Crypto Signal"
        assert page.get_by_text("인터넷에 연결해 주세요").is_visible()
        assert not page.locator("#btc-live-analysis, #btc-chart-reader").count()
        context.set_offline(False)
        page.get_by_role("link", name="다시 연결하기").click()
        page.locator("#btc-chart-reader").wait_for(timeout=45000)
        page.screenshot(path="/tmp/btc-pwa-online.png")
        context.close()
        return {
            "installability_errors": errors,
            "standalone_manifest": True,
            "worker_control": True,
            "offline_recovery": True,
            "cached_files": keys,
        }


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
    crypto.locator('#binance[data-history="ready"]').wait_for()
    crypto.evaluate("window.__pwaToken=Math.random()")
    token = crypto.evaluate("window.__pwaToken")
    cdp = context.new_cdp_session(page)
    results = []
    for tf, label in (("1h", "1시간"), ("4h", "4시간"), ("1d", "일봉"), ("1w", "주봉"), ("1M", "월봉")):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "tf=>document.querySelector('#btc-chart-reader')?.dataset.timeframe===tf && [...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.timeframe===tf)",
            arg=tf,
        )
        plot = page.locator(".js-plotly-plot:visible").first
        region = plot.locator(".nsewdrag").first
        region.scroll_into_view_if_needed()
        box = region.bounding_box()
        x, y = box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.4
        baseline = event_log.read_text() if event_log else None
        original = ranges(plot)
        touch(cdp, "touchStart", [(x, y)])
        page.wait_for_timeout(80)
        first = page.locator("#btc-chart-reader").get_attribute("data-index")
        for step in range(1, 6):
            touch(cdp, "touchMove", [(x + box["width"] * 0.12 * step, y)])
            page.wait_for_timeout(40)
        second = page.locator("#btc-chart-reader").get_attribute("data-index")
        assert first != second, (tf, first, second)
        touch(cdp, "touchEnd")
        assert ranges(plot) == original
        # Compare every displayed value against that exact candle/indicator,
        # including absent long moving-average history on the monthly chart.
        mismatches = plot.evaluate("""p=>{
          const host=document.querySelector('#btc-chart-reader'),i=Number(host.dataset.index),c=p.data[0];
          const read=a=>a.bdata?new ({f8:Float64Array,f4:Float32Array}[a.dtype])(Uint8Array.from(atob(a.bdata),x=>x.charCodeAt(0)).buffer):a;
          const expected=Object.fromEntries(['open','high','low','close'].map(key=>[key,read(c[key])[i]]));
          for(const [index,key] of Object.entries(p.layout.meta.btcLive.overlays))expected[key]=p.calcdata[index][i]?.y;
          return Object.entries(expected).flatMap(([key,n])=>{
            const text=host.querySelector(`[data-field="${key}"]`)?.textContent;
            return !Number.isFinite(n)?text==='—'?[]:[{key,n,text}]:Math.abs(Number(text.replaceAll(',',''))-n)<.0051?[]:[{key,n,text}];
          });
        }""")
        assert not mismatches, (tf, mismatches)
        page.get_by_role("button", name="이전 차트 구간").tap()
        page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.mode==='inspect'")
        page.wait_for_timeout(100)
        shifted = ranges(plot)
        assert shifted["xaxis"] != original["xaxis"], tf
        page.get_by_role("button", name="최신 봉", exact=True).tap()
        page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.mode==='latest'")
        assert int(page.locator("#btc-chart-reader").get_attribute("data-index")) == plot.evaluate(
            "p=>p.data[0].x.length-1"
        )
        if baseline is not None:
            assert event_log.read_text() == baseline, "Inspection/navigation reran Python"
        assert (
            crypto.evaluate("window.__pwaToken") == token
            and crypto.evaluate("window.__quoteSockets.length") == 3
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        results.append(
            {"timeframe": tf, "finger_tracking": True, "ohlc_ema_bands": True, "local_navigation": True}
        )
    page.get_by_role("radio", name="일봉", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.timeframe==='1d'")
    page.get_by_role("button", name="지표", exact=True).tap()
    page.get_by_role("radio", name="상세", exact=True).tap()
    page.get_by_text("표시할 봉 수", exact=True).wait_for()
    page.keyboard.press("Escape")
    page.locator('[data-testid="stMain"]').evaluate("e=>e.scrollTop=0")
    page.screenshot(path=f"/tmp/btc-pwa-top-{width}.png")
    assert not errors, errors
    cleanup(page, crypto)
    context.close()
    return {"width": width, "checks": results, "js_errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as p:
        print(json.dumps(installability(p, args.app_url)), flush=True)
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (390, 820, 1440):
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
