"""Official kline schemas, live charts/forecasts and touch in the real app.

Fixtures demonstrate UI correctness and latency, not forecast accuracy.
"""

import argparse
import json
from pathlib import Path
import time

import pandas as pd
from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport
from check_touch_charts import inspect, touch


def plot_data(page):
    return page.locator(".js-plotly-plot:visible").first.evaluate(
        "p=>({traces:p.data?.map(t=>({name:t.name,length:t.y?.length,tail:t.y?.at?.(-1)})),meta:p.layout?.meta,dataset:{...p.dataset}})"
    )


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    install_quote_transport(page)
    page.add_init_script(
        "window.__livePlot=()=>[...document.querySelectorAll('.js-plotly-plot')].find(p=>p.getClientRects().length)"
    )
    fixture = MarketFixture(page)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.wait_for_function(
        "()=>window.__livePlot()?.data?.length && document.querySelector('#btc-live-analysis')",
        timeout=45000,
    )
    crypto = next(f for f in page.frames if f.locator("#binance").count())
    crypto.locator('#binance[data-history="ready"]').wait_for()
    fixture.rest = False
    payload = page.locator("#btc-live-analysis").evaluate("e=>JSON.parse(e.dataset.seeds)")
    templates = []
    for tf, seed in payload["frames"].items():
        start = pd.Timestamp(seed["end"], unit="ms", tz="UTC")
        end = start + (
            pd.DateOffset(months=1)
            if tf == "1M"
            else pd.Timedelta(hours={"1h": 1, "4h": 4, "1d": 24, "1w": 168}[tf])
        )
        templates.append(
            {
                "e": "kline",
                "E": 0,
                "s": "BTCUSDT",
                "k": {
                    "s": "BTCUSDT",
                    "i": tf,
                    "t": seed["end"],
                    "T": int(end.timestamp() * 1000) - 1,
                    "o": "100000",
                    "h": "120000",
                    "l": "80000",
                    "c": "100300",
                    "v": "18",
                    "x": False,
                },
            }
        )
    crypto.evaluate(
        """packets=>{
      window.__livePackets=packets;window.__livePrice=100300;window.__livePaused=false;window.__livePauseCandles=false;
      window.__emitLive=()=>{
        if(window.__livePaused)return;
        const socket=window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance') && s.readyState===1).at(-1);
        if(!socket)return;
        const now=Date.now();
        if(!window.__livePauseCandles)for(const p of packets){p.E=now;p.k.c=String(window.__livePrice);socket.emit(JSON.stringify({data:p}));}
        socket.emit(JSON.stringify({data:{e:'aggTrade',E:now,s:'BTCUSDT',p:String(window.__livePrice)}}));
        window.__quoteSockets.filter(s=>s.url.includes('api.upbit.com/websocket') && s.readyState===1).at(-1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:0.01,timestamp:now}));
      };
      window.__liveTimer=setInterval(window.__emitLive,1000);window.__emitLive();
    }""",
        templates,
    )
    page.wait_for_function(
        "()=>[...document.querySelectorAll('#btc-live-analysis article')].every(e=>e.dataset.status==='실시간 · 잠정')"
    )
    page.evaluate(
        """()=>{window.__livePaints=0;const original=Plotly.restyle;Plotly.restyle=function(...args){window.__livePaints++;return original.apply(this,args);};}"""
    )
    sockets = crypto.evaluate("window.__quoteSockets.length")
    assert page.locator("iframe").count() == 1
    latencies = []
    activate = "tap" if width < 1000 else "click"
    for tf, label in (("1h", "1시간"), ("4h", "4시간"), ("1d", "일봉"), ("1w", "주봉"), ("1M", "월봉")):
        getattr(page.get_by_role("radio", name=label, exact=True), activate)()
        page.wait_for_function("tf=>window.__livePlot()?.layout.meta?.btcLive?.timeframe===tf", arg=tf)
        price = 100400 + len(latencies) * 100
        baseline = event_log.read_text() if event_log else None
        start = time.perf_counter()
        crypto.evaluate("price=>{window.__livePrice=price;window.__emitLive();}", price)
        page.wait_for_function(
            "([tf,p])=>{const c=window.__livePlot();return c?.dataset.liveTimeframe===tf && c.dataset.livePrice===String(p) && c.data[0].close.at(-1)===p && c.data[0].x.length<=120;}",
            arg=[tf, price],
        )
        latencies.append(round((time.perf_counter() - start) * 1000, 1))
        assert page.locator(".btc-chart-summary").inner_text().count("진행 중 봉") == 1
        assert page.locator(".js-plotly-plot:visible").first.evaluate(
            "p=>new Set(p.data[0].x).size===p.data[0].x.length && p.data[0].close.length===p.data[0].x.length"
        )
        if baseline is not None:
            assert event_log.read_text() == baseline, "Live candle re-entered Python analysis"
    # Toggle cached overlays; latest candle must survive the new parent chart.
    getattr(page.get_by_role("radio", name="일봉", exact=True), activate)()
    page.wait_for_function("()=>window.__livePlot()?.layout.meta?.btcLive?.timeframe==='1d'")
    getattr(page.get_by_text("이동평균선", exact=True), activate)()
    page.wait_for_function(
        "()=>Object.values(window.__livePlot()?.layout.meta?.btcLive?.overlays ?? {}).includes('ema_20')"
    )
    getattr(page.get_by_text("볼린저밴드", exact=True), activate)()
    try:
        page.wait_for_function(
            "()=>{const p=window.__livePlot();return Object.values(p?.layout.meta?.btcLive?.overlays ?? {}).includes('bb_middle') && p.dataset.livePrice==='100800';}"
        )
    except Exception:
        print(json.dumps({"overlay_diagnostic": plot_data(page), "errors": errors}), flush=True)
        raise
    try:
        page.wait_for_function(
            "()=>{const p=window.__livePlot();return p.data.filter(t=>t.name==='EMA 20')[0]?.y?.length===120;}"
        )
    except Exception:
        print(json.dumps({"overlay_values": plot_data(page), "errors": errors}), flush=True)
        raise
    crypto.evaluate("window.__livePaused=true")
    plot = page.locator(".js-plotly-plot:visible").first
    cdp = context.new_cdp_session(page)
    inspect(page, cdp, plot, event_log, "live candle and overlays")
    # Bad/out-of-order/wrong-symbol packets cannot move a candle or its analysis.
    original = plot.evaluate("p=>JSON.stringify(p.data)")
    crypto.evaluate(
        """()=>{const s=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance'));const p=JSON.parse(JSON.stringify(window.__livePackets[2]));p.E-=10000;p.k.c='110000';s.emit(JSON.stringify({data:p}));p.E=Date.now();p.s='ETHUSDT';s.emit(JSON.stringify({data:p}));}"""
    )
    page.wait_for_timeout(600)
    assert plot.evaluate("p=>JSON.stringify(p.data)") == original
    # A burst is coalesced; one forming candle never turns into many candles.
    baseline = event_log.read_text() if event_log else None
    before = page.evaluate("window.__livePaints")
    crypto.evaluate(
        """()=>{const s=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance'));let last=Date.now()-200;for(let i=0;i<200;i++){const p=JSON.parse(JSON.stringify(window.__livePackets[2]));p.E=last+i;p.k.c=String(100900+i);s.emit(JSON.stringify({data:p}));}}"""
    )
    page.wait_for_function("()=>window.__livePlot()?.dataset.livePrice==='101099'")
    burst_calls = page.evaluate("window.__livePaints") - before
    assert burst_calls <= 10 and plot.evaluate("p=>p.data[0].x.length") == 120
    if baseline is not None:
        assert event_log.read_text() == baseline
    assert crypto.evaluate("window.__quoteSockets.length") == sockets
    # Observe a deliberate source delay, then resume the same existing socket.
    crypto.evaluate("window.__livePaused=false;window.__livePauseCandles=true;window.__emitLive()")
    page.wait_for_function(
        "()=>document.querySelector('.btc-chart-summary')?.innerText.includes('수신 지연')", timeout=18000
    )
    assert page.locator("#btc-live-analysis").inner_text().count("수신 지연") == 5
    crypto.evaluate("window.__livePauseCandles=false;window.__emitLive()")
    page.wait_for_function("()=>window.__livePlot()?.dataset.livePrice==='100800'")
    # Quote ticks continue during the missing kline interval; the same connection
    # recovers without accepting a stale candle or adding a new analysis socket.
    sockets = crypto.evaluate("window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance')).length")
    getattr(page.get_by_role("tab", name="미래 예측", exact=True), activate)()
    page.locator("#btc-live-forecast").wait_for(timeout=45000)
    page.wait_for_function(
        "()=>window.__livePlot()?.layout.meta?.btcLive?.kind==='forecast' && document.querySelector('.btc-direction-reasons')"
    )
    origin = pd.Timestamp.now(tz="UTC").normalize()
    for label, months in (("1주", 0), ("1개월", 1), ("3개월", 3), ("6개월", 6)):
        days = 7 if months == 0 else ((origin + pd.DateOffset(months=months)) - origin).days
        getattr(page.get_by_role("radio", name=label, exact=True), activate)()
        try:
            page.wait_for_function(
                "days=>{const m=window.__livePlot()?.layout.meta?.btcLive;return m?.kind==='forecast' && m.offsets.at(-1)===days*86400000;}",
                arg=days,
            )
        except Exception:
            print(
                json.dumps(
                    {"period": label, "days": days, "forecast_diagnostic": plot_data(page), "errors": errors}
                ),
                flush=True,
            )
            raise
        plot = page.locator(".js-plotly-plot:visible").first
        meta = plot.evaluate("p=>p.layout.meta.btcLive")
        assert meta["offsets"][-1] == days * 86400000
        base = plot.evaluate("p=>JSON.stringify(p.data.filter(t=>t.meta?.direction))")
        baseline = event_log.read_text() if event_log else None
        price = 101000 + len(meta["offsets"])
        crypto.evaluate("price=>{window.__livePrice=price;window.__emitLive();}", price)
        page.wait_for_function(
            "p=>{const c=window.__livePlot();return c?.dataset.livePrice===String(p) && Math.abs(c.data.at(-1).y[0]-p)<1e-6;}",
            arg=price,
        )
        assert plot.evaluate("p=>JSON.stringify(p.data.filter(t=>t.meta?.direction))") == base
        assert "기존 지표·유사 사례" in page.locator("#btc-live-forecast").inner_text()
        assert plot.evaluate("p=>p.data.filter(t=>t.meta?.direction).length") == 3
        if baseline is not None:
            assert event_log.read_text() == baseline, "Price tick re-entered forecast/calibration"
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    # Real updates continue arriving while a finger inspects a fixed plot.
    region = plot.locator(".nsewdrag").first
    region.scroll_into_view_if_needed()
    rect = region.bounding_box()
    x, y = rect["x"] + rect["width"] * 0.4, rect["y"] + rect["height"] * 0.5
    touch(cdp, "touchStart", [(x, y)])
    frozen = plot.evaluate("p=>JSON.stringify(p.data)")
    page.wait_for_timeout(1200)
    assert plot.evaluate("p=>JSON.stringify(p.data)") == frozen, "Live redraw interrupted finger inspection"
    assert any(c.isdigit() for c in plot.locator(".hoverlayer").text_content())
    touch(cdp, "touchEnd")
    crypto.evaluate("window.__livePaused=true")
    # Let the last coalesced tick finish after releasing the live inspection.
    page.wait_for_timeout(750)
    inspect(page, cdp, plot, event_log, "live conditional forecast")
    assert not errors, errors
    assert page.locator("iframe").count() == 1
    assert (
        crypto.evaluate("window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance')).length")
        == sockets
    )
    assert not page.locator('[data-testid="stException"]').count()
    page.screenshot(path=f"/tmp/btc-realtime-forecast-{width}.png", full_page=True)
    crypto.evaluate("clearInterval(window.__liveTimer)")
    cleanup(page, crypto)
    context.close()
    return {
        "width": width,
        "five_live_candles": "passed",
        "four_forecast_periods": "passed",
        "touch_scroll_hover": "passed",
        "protocol_stale_resume": "passed",
        "burst_restyles": burst_calls,
        "extra_iframes": 0,
        "python_tick_runs": 0,
        "fixture_candle_latency_ms": latencies,
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
