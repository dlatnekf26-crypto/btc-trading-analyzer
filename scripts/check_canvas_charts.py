"""Verify actual chart pixels, pan/zoom, exchange cases and SVG fallback."""

import argparse
import json

from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, cleanup, select_market
from check_chart_gestures import gesture_check


READY = """()=>{const p=[...document.querySelectorAll('.js-plotly-plot')].find(p=>p.getClientRects().length);return p?.layout?.meta?.btcLive?.kind==='market'&&p.dataset.canvasRevision===p.layout.uirevision&&p.layout.meta.btcLive.symbol===document.querySelector('#btc-live-selection')?.dataset.symbol;}"""


def pixels(plot):
    return plot.evaluate("""p=>{
      const read=a=>a?.bdata?Array.from(new ({f8:Float64Array,f4:Float32Array}[a.dtype])(Uint8Array.from(atob(a.bdata),c=>c.charCodeAt(0)).buffer)):a;
      const c=p.data.find(t=>t.type==='candlestick'),x=p._fullLayout.xaxis,y=p._fullLayout.yaxis;
      const canvas=p.querySelector('.btc-canvas-layer canvas[data-pane=xy]'),ctx=canvas.getContext('2d'),ratio=canvas.width/x._length;
      const opens=read(c.open),closes=read(c.close),found=[];
      for(let i=0;i<c.x.length;i++){
        const px=x.d2p(c.x[i]),py=(y.c2p(opens[i])+y.c2p(closes[i]))/2;
        if(px<3||px>x._length-3||py<3||py>y._length-3)continue;
        const color=closes[i]>=opens[i]?[239,63,80]:[37,99,235];
        const data=ctx.getImageData(Math.round(px*ratio)-1,Math.round(py*ratio)-1,3,3).data;
        if(Array.from({length:9},(_,j)=>j*4).some(k=>data[k+3]>80&&color.every((n,j)=>Math.abs(n-data[k+j])<12)))found.push(i);
      }
      return {nodes:p.querySelectorAll('*').length,paths:p.querySelectorAll('path').length,matched_candles:found.length,
        canvases:[...p.querySelectorAll('.btc-canvas-layer canvas')].map(c=>({pane:c.dataset.pane,width:c.width,height:c.height,ink:c.getContext('2d').getImageData(0,0,c.width,c.height).data.some((n,i)=>i%4===3&&n>0)}))};
    }""")


def verify(browser, width, url, fallback=False):
    context = browser.new_context(viewport={"width": width, "height": 1000}, has_touch=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    MarketFixture(page)
    if fallback:
        page.add_init_script(
            """const context=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(...args){return this.closest('.btc-canvas-layer')?null:context.apply(this,args);};"""
        )
    page.goto(url.rstrip("/") + "/?market=BTC&view=chart")
    page.wait_for_function(READY, timeout=60000)
    bridge = next(frame for frame in page.frames if frame.locator("#binance").count())
    plot = page.locator(".js-plotly-plot:visible").first
    cases = []
    for label, frame in (
        ("5분", "5m"),
        ("15분", "15m"),
        ("1시간", "1h"),
        ("4시간", "4h"),
        ("일봉", "1d"),
        ("주봉", "1w"),
        ("월봉", "1M"),
    ):
        page.get_by_role("radio", name=label, exact=True).click()
        try:
            page.wait_for_function(
                "tf=>document.querySelector('#btc-chart-reader')?.dataset.timeframe===tf&&document.querySelector('.js-plotly-plot')?.layout?.meta?.btcLive?.timeframe===tf",
                arg=frame,
            )
        except Exception:
            print(
                json.dumps(
                    {
                        "failed_frame": frame,
                        "state": page.evaluate(
                            "()=>({reader:document.querySelector('#btc-chart-reader')?.dataset.timeframe,plot:document.querySelector('.js-plotly-plot')?.layout?.meta?.btcLive?.timeframe,mode:document.querySelector('.js-plotly-plot')?.dataset.canvasRendering,radio:[...document.querySelectorAll('input[type=radio]:checked')].map(n=>n.value)})"
                        ),
                        "errors": errors,
                    }
                ),
                flush=True,
            )
            raise
        page.wait_for_function(READY)
        if fallback:
            assert plot.get_attribute("data-canvas-rendering") == "fallback"
            assert plot.locator(".boxlayer path").count() > 0
        else:
            result = pixels(plot)
            assert len(result["canvases"]) == 4 and result["matched_candles"] > 0, (label, result)
            assert not plot.locator(".boxlayer path").count()
            cases.append({"frame": label, **result})
        print(json.dumps({"frame": frame, "fallback": fallback, "passed": True}), flush=True)
    cdp = context.new_cdp_session(page)
    gesture_check(page, cdp, plot, None, "Canvas" if not fallback else "SVG fallback")
    if not fallback:
        page.get_by_role("radio", name="일봉", exact=True).click()
        page.wait_for_function(
            "()=>document.querySelector('.js-plotly-plot')?.layout?.meta?.btcLive?.timeframe==='1d'"
        )
        page.wait_for_function(READY)
        for code in ("ETH", "SOL", "XRP", "SAMSUNG", "AAPL", "KOSPI", "NQ", "SP500"):
            symbol = page.locator(".board-asset").evaluate_all(
                "(nodes,code)=>nodes.find(n=>n.querySelector('.board-symbol')?.textContent===code)?.dataset.quoteSymbol",
                code,
            )
            select_market(
                page, {"SAMSUNG": "삼성전자", "KOSPI": "코스피", "SP500": "S&P 500"}.get(code, code)
            )
            page.wait_for_function(
                "symbol=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.symbol===symbol)",
                arg=symbol,
            )
            page.wait_for_function(READY)
            result = pixels(plot)
            assert len(result["canvases"]) == 4 and result["matched_candles"] > 0, (code, result)
            cases.append({"market": code, **result})
        assert bridge.evaluate("document.body.dataset.bridgeOnly") == "true"
        assert bridge.locator(".dashboard").evaluate("e=>getComputedStyle(e).display") == "none"
    assert not errors, errors
    page.screenshot(path=f"/tmp/btc-canvas-{width}-{'fallback' if fallback else 'native'}.png")
    cleanup(page, bridge)
    context.close()
    return {"width": width, "fallback": fallback, "cases": cases, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--widths", type=int, nargs="+", default=[390, 820, 1440])
    parser.add_argument("--fallback", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(json.dumps(verify(browser, width, args.app_url, args.fallback)), flush=True)
        browser.close()
