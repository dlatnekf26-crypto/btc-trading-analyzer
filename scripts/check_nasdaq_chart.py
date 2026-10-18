"""Exchange chart/forecast isolation, session dates and touch in the fixture app."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, send_macro
from check_touch_charts import inspect
from check_chart_gestures import gesture_check, region_box, touch


def verify(browser, width, url, event_log, market="NQ"):
    symbol, title, card = ("^KS11", "코스피", "kospi") if market == "KOSPI" else ("NQ=F", "NQ", "nq")
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
    page.get_by_role("radio", name=title, exact=True).tap()
    page.wait_for_function("s=>document.querySelector('#btc-chart-reader')?.dataset.symbol===s", arg=symbol)
    crypto.wait_for_function("s=>document.body.dataset.asset===s", arg=symbol)
    assert not crypto.locator('.crypto[data-selected="true"]').count()
    page.wait_for_function("id=>document.querySelectorAll('#macro-'+id).length===1", arg=card)
    assert page.get_by_text("공개 지연 자료", exact=False).is_visible()
    if market == "KOSPI":
        now = page.evaluate("Date.now()")
        send_macro(crypto, symbol, 2850.25, now - 60000, currency="KRW")
        page.locator('#btc-chart-reader [data-field="current"]').get_by_text(
            "2,850.25", exact=True
        ).wait_for()
        send_macro(crypto, symbol, 1, now, currency="USD")
        send_macro(crypto, "BTCUSDT", 1, now, currency="KRW")
        page.wait_for_timeout(100)
        assert page.locator('#btc-chart-reader [data-field="current"]').inner_text() == "2,850.25"
        send_macro(crypto, symbol, 2860.5, now - 30000, currency="KRW")
        page.locator('#btc-chart-reader [data-field="current"]').get_by_text(
            "2,860.50", exact=True
        ).wait_for()
    cdp = context.new_cdp_session(page)
    for tf, label in (
        ("5m", "5분"),
        ("15m", "15분"),
        ("1h", "1시간"),
        ("4h", "4시간"),
        ("1d", "일봉"),
        ("1w", "주봉"),
        ("1M", "월봉"),
    ):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "([tf,s])=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.symbol===s && p.layout.meta.btcLive.timeframe===tf)",
            arg=[tf, symbol],
        )
    plot = page.locator(".js-plotly-plot:visible").first
    inspect(page, cdp, plot, event_log, market + " monthly")
    if market == "KOSPI":
        gesture_check(page, cdp, plot, event_log, "KOSPI monthly")
        box = region_box(page, plot)
        x, y = box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.4
        current = page.locator('#btc-chart-reader [data-field="current"]')
        touch(cdp, "touchStart", [(x, y)])
        page.wait_for_timeout(400)
        before = plot.get_attribute("data-cursor-price")
        send_macro(crypto, symbol, 2870.5, page.evaluate("Date.now()") - 1000, currency="KRW")
        current.get_by_text("2,870.50", exact=True).wait_for()
        touch(cdp, "touchMove", [(x + 20, y + 40)])
        page.wait_for_timeout(80)
        assert before != plot.get_attribute("data-cursor-price")
        assert current.inner_text() == "2,870.50"
        touch(cdp, "touchEnd")
    page.get_by_role("tab", name="미래 예측", exact=True).tap()
    for label, bounds in (
        ("1주", (0, 10)),
        ("2주", (5, 15)),
        ("1개월", (10, 30)),
        ("2개월", (30, 60)),
        ("3개월", (40, 80)),
        ("6개월", (90, 150)),
    ):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "([bounds,s])=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.symbol===s && p.layout.meta.btcLive.kind==='forecast' && Object.keys(p.layout.meta.btcLive.indicatorOverlays ?? {}).length===6 && p.data[3].x.length>bounds[0] && p.data[3].x.length<bounds[1])",
            arg=[bounds, symbol],
        )
        plot = page.locator(".js-plotly-plot:visible").first
        assert not page.locator("#btc-live-forecast").count()
        # Every predicted close is a exchange trading date, never a weekend.
        assert page.evaluate(
            """()=>[...document.querySelectorAll('.js-plotly-plot')]
              .find(p=>p.getClientRects().length && p.layout?.meta?.btcLive?.kind==='forecast')
              .data[3].x.every(x=>![0,6].includes(new Date(new Date(x).getTime()-9*3600000).getUTCDay()))"""
        )
    # Model metadata arrives before Plotly finishes its axis update. Wait for
    # the displayed axes to settle before comparing touch/scroll invariants.
    previous, stable = None, 0
    for _ in range(30):
        current = plot.evaluate("p=>JSON.stringify([p._fullLayout.xaxis.range,p._fullLayout.yaxis.range])")
        stable = stable + 1 if current == previous else 0
        if stable >= 3:
            break
        previous = current
        page.wait_for_timeout(100)
    assert stable >= 3, "Forecast axes did not settle"
    try:
        inspect(page, cdp, plot, event_log, market + " forecast")
    except AssertionError:
        print(
            json.dumps(
                {
                    "forecast_axes_on_failure": plot.evaluate(
                        "p=>({auto:p.dataset.autoScale,range:p._fullLayout.yaxis.range,revision:p.layout.uirevision,rect:p.querySelector('.nsewdrag').getBoundingClientRect().toJSON()})"
                    ),
                    "auto_buttons": page.locator('[data-chart-action="auto"]').evaluate_all(
                        "es=>es.map(e=>({id:e.closest('.btc-chart-reader').id,pressed:e.getAttribute('aria-pressed')}))"
                    ),
                }
            ),
            flush=True,
        )
        raise
    if market == "KOSPI":
        gesture_check(page, cdp, plot, event_log, "KOSPI 6month forecast")
    assert "pt" in page.locator("#btc-forecast-reader").inner_text()
    assert not crypto.evaluate(
        "window.__subscriptions.some(s=>s.params?.some(p=>p.toLowerCase().startsWith('nq') || p.includes('^KS11'))) "
    )
    assert (
        crypto.evaluate("window.__nqToken") == token and crypto.evaluate("window.__quoteSockets.length") == 3
    )
    assert page.locator("iframe").count() == 1
    page.screenshot(path=f"/tmp/btc-{market.lower()}-forecast-{width}.png")
    page.get_by_role("radio", name="ETH", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('#btc-forecast-reader')?.dataset.symbol==='ETHUSDT'")
    assert page.locator("#btc-live-forecast").count() == 1 and crypto.evaluate("window.__nqToken") == token
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth") and not errors, errors
    crypto.evaluate("clearInterval(window.__nqFeed)")
    cleanup(page, crypto)
    context.close()
    return {
        "width": width,
        market + "_seven_frames_six_horizons": True,
        "crypto_isolation_and_return": True,
        "pan_pinch_auto_and_held_current_quote": market == "KOSPI",
        "js_errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--market", choices=("NQ", "KOSPI"), default="NQ")
    parser.add_argument("--widths", type=int, nargs="+", default=[390, 820, 1440])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(json.dumps(verify(browser, width, args.app_url, args.event_log, args.market)), flush=True)
        browser.close()
