"""Time the actual board/detail/forecast browser flow against an offline server."""

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright
from benchmark_chart_gestures import MARKET_READY
from check_live_widget import MarketFixture, install_quote_transport, cleanup


def measure(browser, url, width, cpu):
    context = browser.new_context(viewport={"width": width, "height": 1000}, has_touch=True)
    page = context.new_page()
    install_quote_transport(page)
    MarketFixture(page)
    errors, frames, stages = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("websocket", lambda socket: socket.on("framereceived", lambda data: frames.append(len(data))))
    cdp = context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})

    def step(label, action, ready):
        start, before = time.perf_counter(), sum(frames)
        action()
        page.wait_for_function(ready, timeout=60000)
        stages.append(
            {
                "stage": label,
                "seconds": round(time.perf_counter() - start, 4),
                "socket_bytes": sum(frames) - before,
            }
        )
        print(json.dumps({"progress": stages[-1]}), flush=True)

    step(
        "board",
        lambda: page.goto(url),
        "()=>document.querySelectorAll('[data-quote-symbol].board-asset').length===15",
    )
    step(
        "quotes",
        lambda: None,
        "()=>[...document.querySelectorAll('.board-asset [data-quote-field=price]')].every(e=>e.textContent!=='—')",
    )
    assert not page.locator(".js-plotly-plot").count()
    step(
        "detail",
        lambda: page.get_by_role("button", name="비트코인 차트 열기", exact=True).click(),
        "()=> (" + MARKET_READY + ")(document.querySelector('.js-plotly-plot'))",
    )
    step(
        "timeframe_5m",
        lambda: page.get_by_role("radio", name="5분", exact=True).click(),
        "()=>{const p=document.querySelector('.js-plotly-plot');return p?.layout?.meta?.btcLive?.timeframe==='5m'&&document.querySelector('#btc-chart-reader')?.dataset.timeframe==='5m'&&("
        + MARKET_READY
        + ")(p);}",
    )
    step(
        "timeframe_1d",
        lambda: page.get_by_role("radio", name="일봉", exact=True).click(),
        "()=>{const p=document.querySelector('.js-plotly-plot');return p?.layout?.meta?.btcLive?.timeframe==='1d'&&document.querySelector('#btc-chart-reader')?.dataset.timeframe==='1d'&&("
        + MARKET_READY
        + ")(p);}",
    )
    chart = page.locator(
        ".js-plotly-plot:visible"
    ).first.evaluate("""p=>({nodes:p.querySelectorAll('*').length,paths:p.querySelectorAll('path').length,
      layers:[...p.querySelectorAll('.overplot>g')].map(g=>({tag:g.tagName,class:g.getAttribute('class'),transform:g.getAttribute('transform'),children:[...g.children].map(n=>({tag:n.tagName,class:n.getAttribute('class'),transform:n.getAttribute('transform'),html:n.outerHTML.slice(0,180)}))})),
      axes:Object.fromEntries(Object.entries(p._fullLayout._plots).map(([k,v])=>[k,{x:v.xaxis._offset,y:v.yaxis._offset,width:v.xaxis._length,height:v.yaxis._length}]))})""")
    step(
        "forecast",
        lambda: page.get_by_role("tab", name="미래 예측", exact=True).click(),
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.kind==='forecast')",
    )
    step(
        "forecast_3mo",
        lambda: page.get_by_role("radio", name="3개월", exact=True).click(),
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.kind==='forecast'&&p.layout.meta.btcLive.offsets.at(-1)>=70*86400000)",
    )
    resources = page.evaluate(
        "()=>performance.getEntriesByType('resource').filter(r=>r.name.includes('/static/')).map(r=>({name:r.name.split('/').at(-1),bytes:r.encodedBodySize||r.transferSize,duration:r.duration}))"
    )
    assert not errors, errors
    cleanup(page, next(frame for frame in page.frames if frame.locator("#binance").count()))
    context.close()
    return {
        "width": width,
        "cpu_rate": cpu,
        "stages": stages,
        "static_bytes": sum(r["bytes"] for r in resources),
        "chart": chart,
        "resources": sorted(resources, key=lambda r: r["bytes"], reverse=True)[:8],
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--width", type=int, default=390)
    parser.add_argument("--cpu", type=float, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for _ in range(args.repeats):
            results.append(measure(browser, args.app_url, args.width, args.cpu))
            print(json.dumps(results[-1]), flush=True)
        browser.close()
    args.output.write_text(json.dumps(results, indent=2))
