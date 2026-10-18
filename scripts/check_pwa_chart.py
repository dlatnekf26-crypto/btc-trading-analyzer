"""Actual installability/offline navigation and candle inspection in Chromium.

Exchange fixtures control prices; this does not measure exchange latency or Safari.
"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, install_quote_transport


def installability(playwright, url):
    with TemporaryDirectory(prefix="btc-pwa-profile-") as profile:
        context = playwright.chromium.launch_persistent_context(
            profile, executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        page = context.pages[0]
        install_quote_transport(page)
        MarketFixture(page)
        page.goto(url.split("?")[0])
        page.get_by_role("button", name="비트코인 차트 열기", exact=True).wait_for(timeout=45000)
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
        page.get_by_role("button", name="비트코인 차트 열기", exact=True).wait_for(timeout=45000)
        page.get_by_role("button", name="비트코인 차트 열기", exact=True).click()
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
    from check_chart_gestures import verify as current_verify

    return current_verify(browser, width, url, event_log)


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
