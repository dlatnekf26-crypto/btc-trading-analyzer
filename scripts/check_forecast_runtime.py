"""Exercise live forecast caching and metadata replacement in actual Plotly DOM."""

import argparse
import json

from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, cleanup
from benchmark_chart_gestures import MARKET_READY


def verify(browser, width, url):
    context = browser.new_context(viewport={"width": width, "height": 1000}, has_touch=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    fixture = MarketFixture(page)
    page.goto(url.rstrip("/") + "/?market=BTC&view=chart")
    page.wait_for_function(
        "()=> (" + MARKET_READY + ")(document.querySelector('.js-plotly-plot'))", timeout=60000
    )
    page.get_by_role("tab", name="미래 예측", exact=True).click()
    page.get_by_role("radio", name="6개월", exact=True).click()
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.layout?.meta?.btcLive?.kind==='forecast'&&p.layout.meta.btcLive.offsets.at(-1)>170*86400000)"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    plot.scroll_into_view_if_needed()
    fixture.rest = False
    bridge = next(f for f in page.frames if f.locator("#binance").count())
    bridge.evaluate("""()=>{
      window.__forecastPrice=100001;
      window.__forecastEmit=()=>{
        const socket=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);
        socket?.emit(JSON.stringify({data:{e:'aggTrade',E:Date.now(),s:'BTCUSDT',p:String(window.__forecastPrice)}}));
      };
      window.__forecastTimer=setInterval(window.__forecastEmit,600);window.__forecastEmit();
    }""")
    try:
        page.wait_for_function(
            "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.kind==='forecast'&&p.dataset.livePrice==='100001')"
        )
    except Exception:
        print(
            json.dumps(
                {
                    "diagnostic": page.evaluate(
                        "()=>({plots:[...document.querySelectorAll('.js-plotly-plot')].map(p=>({meta:p.layout?.meta?.btcLive?.kind,symbol:p.layout?.meta?.btcLive?.symbol,baseAt:p.layout?.meta?.btcLive?.baseAt,data:{...p.dataset},box:p.getBoundingClientRect().toJSON()})),card:document.querySelector('#btc-live-forecast')?.textContent,selection:document.querySelector('#btc-live-selection')?.dataset.symbol})"
                    ),
                    "bridge": bridge.evaluate(
                        "()=>({price:document.querySelector('#binance .price')?.textContent,asset:document.body.dataset.asset,sockets:window.__quoteSockets.map(s=>({url:s.url,ready:s.readyState}))})"
                    ),
                    "errors": errors,
                }
            ),
            flush=True,
        )
        raise

    before = plot.evaluate(
        "p=>{window.__forecastPlot=p;const m=p.layout.meta.btcLive;return {last:m.center.at(-1),anchor:m.anchor};}"
    )
    # Keep revision and plot.data; update only the server model's identity.
    plot.evaluate(
        "p=>{const m=p.layout.meta.btcLive;p.layout.meta.btcLive={...m,center:m.center.map(v=>v*1.01)};}"
    )
    expected = before["last"] * 1.01 * 100001 / before["anchor"]
    page.wait_for_function(
        "expected=>{const p=window.__forecastPlot,m=p.layout.meta.btcLive;return Math.abs(p.data[m.liveIndices[2]].y.at(-1)-expected)<1e-7;}",
        arg=expected,
    )
    plot.evaluate("p=>p.style.display='none'")
    page.wait_for_timeout(200)  # Allow the real IntersectionObserver to deliver.
    bridge.evaluate("window.__forecastPrice=100002;window.__forecastEmit()")
    page.wait_for_function(
        "()=>document.querySelector('#btc-live-forecast .btc-live-forecast-range')?.textContent.includes('100,002.00')"
    )
    assert page.evaluate("window.__forecastPlot.dataset.livePrice") == "100001", "Offscreen plot was redrawn"
    page.evaluate("window.__forecastPlot.style.display=''")
    plot.scroll_into_view_if_needed()
    page.wait_for_function("()=>window.__forecastPlot.dataset.livePrice==='100002'")
    assert not errors, errors
    bridge.evaluate("clearInterval(window.__forecastTimer)")
    cleanup(page, bridge)
    context.close()
    return {
        "width": width,
        "six_month_live_path": True,
        "same_revision_model_replaced": True,
        "offscreen_card_without_plot_work": True,
        "visible_resume": True,
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--widths", type=int, nargs="+", default=[390, 820, 1440])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(json.dumps(verify(browser, width, args.app_url)), flush=True)
        browser.close()
