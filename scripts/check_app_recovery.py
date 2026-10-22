"""Check saved-page restoration, offline/startup recovery and reload-loop limits.

--root-failure/--health-failure refer to the optional local fixture middleware;
never point these files at production configuration.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, cleanup


def ready(page):
    page.locator(".board-asset").first.wait_for(timeout=60000)
    page.wait_for_function(
        "()=>!document.getElementById('status')&&document.querySelector('[data-quote-symbol=BTCUSDT]')"
    )
    return next(frame for frame in page.frames if frame.locator("#binance").count())


def verify(browser, width, url, root_failure=None, health_failure=None):
    context = browser.new_context(viewport={"width": width, "height": 1000}, has_touch=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    fixture = MarketFixture(page)
    target = url.rstrip("/") + "/?source=pwa"
    page.goto(target)
    bridge = ready(page)
    bridge.wait_for_function(
        "window.__quoteSockets.some(s=>s.url.includes('data-stream.binance')&&s.readyState===1)"
    )
    # Ordinary background/foreground and network restoration reconnect in place.
    origin = page.evaluate("performance.timeOrigin")
    bridge.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))"
    )
    assert bridge.evaluate("window.__quoteSockets.every(s=>s.readyState===3)")
    bridge.evaluate(
        "Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))"
    )
    bridge.wait_for_function("window.__quoteSockets.filter(s=>s.readyState===1).length===3")
    bridge.evaluate("dispatchEvent(new Event('online'))")
    bridge.wait_for_function("window.__quoteSockets.filter(s=>s.readyState===1).length===3")
    assert page.evaluate("performance.timeOrigin") == origin
    # A persisted page was previously restored with every connection closed.
    with page.expect_navigation(wait_until="domcontentloaded"):
        bridge.evaluate(
            "window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))"
        )
    bridge = ready(page)
    bridge.wait_for_function(
        "window.__quoteSockets.some(s=>s.url.includes('data-stream.binance')&&s.readyState===1)"
    )
    fixture.rest = False
    bridge.evaluate(
        "()=>window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance')&&s.readyState===1).at(-1).emit(JSON.stringify({data:{e:'aggTrade',E:Date.now(),s:'BTCUSDT',p:'100011'}}))"
    )
    page.wait_for_function(
        "()=>document.querySelector('[data-quote-symbol=BTCUSDT] .board-price')?.textContent.includes('100,011')"
    )
    assert page.url == target
    page.wait_for_function("()=>navigator.serviceWorker.controller", timeout=30000)
    fixture.rest = True
    context.set_offline(True)
    page.reload(wait_until="domcontentloaded")
    page.locator("#retry").wait_for()
    assert page.locator("#retry").get_attribute("href") == target
    assert not page.locator(".board-price").count(), "Offline page showed a cached market price"
    context.set_offline(False)
    bridge = ready(page)
    assert page.url == target
    failures = []
    if root_failure and health_failure:
        for code in (502, 503, 504):
            root_failure.write_text(str(code))
            health_failure.write_text("503")
            page.reload(wait_until="domcontentloaded")
            page.locator("#retry").wait_for()
            assert page.locator("#retry").get_attribute("href") == target
            health_failure.unlink()
            root_failure.unlink()
            # Reset only the fixture's prior offline-recovery throttle, so each
            # independent server-status case can demonstrate a single recovery.
            page.evaluate(
                "sessionStorage.removeItem('crypto-signal-recovery-at');dispatchEvent(new Event('online'))"
            )
            bridge = ready(page)
            failures.append(code)
        # Health is not proof the root document works. One automatic reload is
        # allowed; a persistently failing root must settle at a manual retry.
        root_failure.write_text("503")
        page.evaluate("sessionStorage.removeItem('crypto-signal-recovery-at')")
        page.reload(wait_until="domcontentloaded")
        page.locator("#retry").wait_for()
        page.wait_for_function(
            "()=>document.getElementById('status')?.textContent.includes('다시 연결하기를 눌러')"
        )
        loaded = page.evaluate("performance.timeOrigin")
        page.wait_for_timeout(1200)
        assert page.evaluate("performance.timeOrigin") == loaded, "Automatic reload loop"
        # A 200 HTML wake-up/login page is never accepted as a healthy endpoint.
        health_failure.write_text("html")
        page.evaluate("sessionStorage.removeItem('crypto-signal-recovery-at')")
        page.reload(wait_until="domcontentloaded")
        page.locator("#retry").wait_for()
        loaded = page.evaluate("performance.timeOrigin")
        page.wait_for_timeout(1200)
        assert page.evaluate("performance.timeOrigin") == loaded
        health_failure.unlink()
        root_failure.unlink()
        page.locator("#retry").click()
        bridge = ready(page)
    assert not errors, errors
    cleanup(page, bridge)
    context.close()
    return {
        "width": width,
        "ordinary_background_online_restore": True,
        "persisted_restore_receives_quotes": True,
        "offline_auto_recovery": True,
        "same_url_preserved": True,
        "server_status_recovery": failures,
        "reload_loop_and_false_health_checked": bool(failures),
        "js_errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--widths", type=int, nargs="+", default=[390, 820, 1440])
    parser.add_argument("--root-failure", type=Path)
    parser.add_argument("--health-failure", type=Path)
    args = parser.parse_args()
    if bool(args.root_failure) != bool(args.health_failure):
        parser.error("Provide both local fixture failure files or neither")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            for width in args.widths:
                print(
                    json.dumps(verify(browser, width, args.app_url, args.root_failure, args.health_failure)),
                    flush=True,
                )
        finally:
            browser.close()
            for path in (args.root_failure, args.health_failure):
                if path:
                    path.unlink(missing_ok=True)
