"""NQ chart/forecast isolation, session dates and touch in the running fixture app."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport
from check_touch_charts import inspect


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    install_quote_transport(page)
    MarketFixture(page)
    page.goto(url)
    page.locator("#btc-chart-reader").wait_for(timeout=45000)
    crypto = next(f for f in page.frames if f.locator("#binance").count())
    crypto.evaluate("window.__nqToken=Math.random()")
    token = crypto.evaluate("window.__nqToken")
    # Keep the mocked sockets alive just as real market tickers would; silence
    # intentionally triggers the production reconnect watchdog after 12/20s.
    crypto.evaluate("""window.__nqFeed=setInterval(()=>{
      const now=Date.now(),b=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance') && s.readyState===1);
      for(const [symbol,price] of [['BTCUSDT',100000],['ETHUSDT',3000],['SOLUSDT',150],['XRPUSDT',1.1532]])b?.emit(JSON.stringify({data:{s:symbol,c:String(price),P:'2.34',E:now}}));
      window.__quoteSockets.find(s=>s.url.includes('api.upbit.com') && s.readyState===1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:.01,timestamp:now}),true);
    },1000);""")
    page.get_by_role("radio", name="NQ", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.symbol==='NQ=F'")
    crypto.wait_for_function("()=>document.body.dataset.asset==='NQ=F'")
    assert not crypto.locator('.crypto[data-selected="true"]').count()
    assert page.locator("#macro-nq").count() == 1
    assert page.get_by_text("공개 지연 자료", exact=False).is_visible()
    cdp = context.new_cdp_session(page)
    for tf, label in (("1h", "1시간"), ("4h", "4시간"), ("1d", "일봉"), ("1w", "주봉"), ("1M", "월봉")):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "tf=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.symbol==='NQ=F' && p.layout.meta.btcLive.timeframe===tf)",
            arg=tf,
        )
    inspect(page, cdp, page.locator(".js-plotly-plot:visible").first, event_log, "NQ monthly")
    page.get_by_role("tab", name="미래 예측", exact=True).tap()
    for label, bounds in (("1주", (0, 10)), ("1개월", (10, 30)), ("3개월", (40, 80)), ("6개월", (90, 150))):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "bounds=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.symbol==='NQ=F' && p.layout.meta.btcLive.kind==='forecast' && Object.keys(p.layout.meta.btcLive.indicatorOverlays ?? {}).length===6 && p.data[3].x.length>bounds[0] && p.data[3].x.length<bounds[1])",
            arg=bounds,
        )
        plot = page.locator(".js-plotly-plot:visible").first
        assert not page.locator("#btc-live-forecast").count()
        # Every predicted close is a US regular trading date, never a weekend.
        assert plot.evaluate(
            "p=>p.data[3].x.every(x=>![0,6].includes(new Date(new Date(x).getTime()-9*3600000).getUTCDay()))"
        )
    inspect(page, cdp, plot, event_log, "NQ forecast")
    assert "pt" in page.locator("#btc-forecast-reader").inner_text()
    assert not crypto.evaluate(
        "window.__subscriptions.some(s=>s.params?.some(p=>p.toLowerCase().startsWith('nq'))) "
    )
    assert (
        crypto.evaluate("window.__nqToken") == token and crypto.evaluate("window.__quoteSockets.length") == 3
    )
    assert page.locator("iframe").count() == 1
    page.screenshot(path=f"/tmp/btc-nq-forecast-{width}.png")
    page.get_by_role("radio", name="ETH", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('#btc-forecast-reader')?.dataset.symbol==='ETHUSDT'")
    assert page.locator("#btc-live-forecast").count() == 1 and crypto.evaluate("window.__nqToken") == token
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth") and not errors, errors
    crypto.evaluate("clearInterval(window.__nqFeed)")
    cleanup(page, crypto)
    context.close()
    return {
        "width": width,
        "NQ_five_frames_four_horizons": True,
        "crypto_isolation_and_return": True,
        "js_errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (390, 820, 1440):
            print(json.dumps(verify(browser, width, args.app_url, args.event_log)), flush=True)
        browser.close()
