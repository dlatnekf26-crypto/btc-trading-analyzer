"""Measure real browser frame gaps/Plotly work on identical fixture chart drags."""

import argparse
import json
from pathlib import Path
import statistics
import time

from playwright.sync_api import sync_playwright
from check_chart_gestures import region_box, touch
from check_live_widget import MarketFixture, cleanup, install_quote_transport


# Axes exist before Plotly finishes drawing. Wait for all four rendered panes,
# or for all Canvas panes, so both versions measure a usable first chart.
MARKET_READY = """p=>{
  if(!p?._fullLayout?.yaxis4||!p.querySelector('.nsewdrag')?.getBoundingClientRect().width)return false;
  if(p.layout.meta?.btcLive?.canvasTraces)return p.dataset.canvasRevision===p.layout.uirevision;
  return ['.subplot.xy .boxlayer path.box','.subplot.x2y2 .barlayer path',
    '.subplot.x3y3 .scatterlayer path.js-line','.subplot.x4y4 .barlayer path'].every(s=>p.querySelector(s));
}"""


def percentile(values, fraction=0.95):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))] if values else 0


def measure(browser, url, width, cpu, profile=None):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    install_quote_transport(page)
    MarketFixture(page)
    cdp = context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})
    cdp.send("Performance.enable")
    started = time.perf_counter()
    page.goto(url)
    page.locator("#btc-chart-reader").wait_for(timeout=60000)
    page.wait_for_function("()=> (" + MARKET_READY + ")(document.querySelector('.js-plotly-plot'))")
    ready = time.perf_counter() - started
    page.get_by_role("radio", name="5분", exact=True).tap()
    page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.timeframe==='5m'")
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.timeframe==='5m'&&p.querySelector('.nsewdrag')?.getBoundingClientRect().width>0)"
    )
    plot = page.locator(".js-plotly-plot:visible").first
    region_box(page, plot)
    page.wait_for_function("()=> (" + MARKET_READY + ")(document.querySelector('.js-plotly-plot'))")
    fingerprint = plot.evaluate("""async p=>{
      const read=a=>a?.bdata?Array.from(new ({f8:Float64Array,f4:Float32Array,i4:Int32Array}[a.dtype])(Uint8Array.from(atob(a.bdata),c=>c.charCodeAt(0)).buffer)):Array.from(a?._inputArray??a??[]);
      const origin=p.data.find(t=>t.type==='candlestick').x[0];
      const source=p.data.filter(t=>t.name!=='canvas pane').map(t=>({type:t.type,name:t.name,x:t.x?.map(v=>v===null?null:v-origin),...Object.fromEntries(['open','high','low','close','y'].filter(k=>t[k]).map(k=>[k,read(t[k])]))}));
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(source))))].map(n=>n.toString(16).padStart(2,'0')).join('');
    }""")
    page.evaluate("""()=>{
      window.__gesturePerf={frames:[],layout:[],input:[],long:[],running:true};
      const perf=window.__gesturePerf,original=Plotly.relayout;
      Plotly.relayout=function(...args){const start=performance.now();const result=original.apply(this,args);result.finally(()=>perf.layout.push(performance.now()-start));return result;};
      let previous;function frame(now){if(previous)perf.frames.push(now-previous);previous=now;if(perf.running)requestAnimationFrame(frame);}requestAnimationFrame(frame);
      let input=0;document.addEventListener('touchmove',()=>input=performance.now(),{capture:true,passive:true});
      new MutationObserver(records=>{if(input&&records.some(r=>r.attributeName==='style'&&(r.target.closest('.overplot')||r.target.closest('.btc-gesture-layer')))){perf.input.push(performance.now()-input);input=0;}}).observe(document.querySelector('.js-plotly-plot'),{subtree:true,attributes:true,attributeFilter:['style']});
      const restore=CanvasRenderingContext2D.prototype.restore;
      CanvasRenderingContext2D.prototype.restore=function(...args){const result=restore.apply(this,args);if(input&&this.canvas.closest('.btc-canvas-layer'))queueMicrotask(()=>{if(input){perf.input.push(performance.now()-input);input=0;}});return result;};
      new PerformanceObserver(list=>{for(const entry of list.getEntries())perf.long.push(entry.duration);}).observe({type:'longtask'});
    }""")
    before = {item["name"]: item["value"] for item in cdp.send("Performance.getMetrics")["metrics"]}
    if profile:
        cdp.send("Profiler.enable")
        cdp.send("Profiler.setSamplingInterval", {"interval": 1000})
        cdp.send("Profiler.start")
    started = time.perf_counter()
    for direction in (1, -1, 1):
        box = region_box(page, plot)
        x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
        touch(cdp, "touchStart", [(x, y)])
        for i in range(1, 25):
            touch(cdp, "touchMove", [(x + direction * box["width"] * 0.3 * i / 24, y)])
            page.wait_for_timeout(16)
        touch(cdp, "touchEnd")
        page.wait_for_timeout(160)
    elapsed = time.perf_counter() - started
    page.wait_for_timeout(200)
    data = page.evaluate("()=>{window.__gesturePerf.running=false;return window.__gesturePerf}")
    after = {item["name"]: item["value"] for item in cdp.send("Performance.getMetrics")["metrics"]}
    if profile:
        profile.write_text(json.dumps(cdp.send("Profiler.stop")["profile"]))
    result = {
        "width": width,
        "cpu_rate": cpu,
        "data_sha256": fingerprint,
        "ready_s": round(ready, 4),
        "gesture_s": round(elapsed, 4),
        "relayouts": len(data["layout"]),
        "relayout_median_ms": round(statistics.median(data["layout"]), 2) if data["layout"] else 0,
        "relayout_p95_ms": round(percentile(data["layout"]), 2),
        "frame_p95_ms": round(percentile(data["frames"]), 2),
        "frames_over_50ms": sum(n > 50 for n in data["frames"]),
        "frames": len(data["frames"]),
        "input_p95_ms": round(percentile(data["input"]), 2),
        "long_tasks": len(data["long"]),
        "long_max_ms": round(max(data["long"], default=0), 2),
        "cpu_ms": {
            key: round((after[key] - before[key]) * 1000, 2)
            for key in ["TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration"]
        },
        "js_errors": errors,
    }
    assert not errors, errors
    cleanup(page, next(f for f in page.frames if f.locator("#binance").count()))
    context.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--width", type=int, default=390)
    parser.add_argument("--cpu", type=float, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--profile", type=Path, help="Diagnostic CPU profile; do not mix its timings with ordinary runs"
    )
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        results = []
        for _ in range(args.repeats):
            value = measure(browser, args.app_url, args.width, args.cpu, args.profile)
            results.append(value)
            print(json.dumps(value), flush=True)
        browser.close()
    if args.output:
        args.output.write_text(json.dumps(results, indent=2))
