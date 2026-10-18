"""Real dashboard: four prices, isolated live candles/forecasts and mobile touch.

Use the development-only offline launcher; fixture prices are not market data.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from check_live_widget import select_market, MarketFixture, cleanup, install_quote_transport
from check_touch_charts import touch

ASSETS = {
    "BTC": ("비트코인", 100000),
    "ETH": ("이더리움", 3000),
    "SOL": ("솔라나", 150),
    "XRP": ("리플", 1.1532),
}


def verify(browser, width, url, event_log):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    install_quote_transport(page)
    page.add_init_script(
        "window.__assetPlot=()=>[...document.querySelectorAll('.js-plotly-plot')].find(p=>p.getClientRects().length)"
    )
    fixture = MarketFixture(page)
    page.goto(url)
    page.wait_for_function("()=>window.__assetPlot()?.data?.length", timeout=45000)
    cdp = context.new_cdp_session(page)
    results = []
    transport_token = None
    history_requests = None
    last_prices = {}
    for code, (name, price) in ASSETS.items():
        select_market(page, code)
        symbol = code + "USDT"
        page.wait_for_function(
            "s=>document.querySelector('#btc-live-analysis')?.dataset.symbol===s", arg=symbol
        )
        page.get_by_role("tab", name="시장 개요", exact=True).tap()
        print(json.dumps({"width": width, "checking_asset": code}), flush=True)
        page.wait_for_function(
            "s=>document.querySelector('#btc-live-analysis')?.dataset.symbol===s && window.__assetPlot()?.layout.meta?.btcLive?.symbol===s",
            arg=symbol,
        )
        crypto = next(f for f in page.frames if f.locator("#binance").count())
        crypto.locator('.crypto[data-selected="true"]').wait_for()
        if not crypto.locator(".quote-extra").evaluate("e=>e.open"):
            crypto.locator(".quote-extra summary").tap()
        crypto.wait_for_function(
            "()=>document.querySelector('#solana .price span')?.textContent!=='—' && document.querySelector('#ripple .price span')?.textContent!=='—'"
        )
        assert crypto.locator(".crypto").count() == 4
        assert (
            crypto.locator("#solana .price span").text_content() == f"{last_prices.get('SOL', 150.25):,.2f}"
        ), crypto.locator("#solana .price span").text_content()
        assert (
            crypto.locator("#ripple .price span").text_content() == f"{last_prices.get('XRP', 1.1532):,.4f}"
        )
        assert page.locator("iframe").count() == 1
        if transport_token is None:
            crypto.evaluate("window.__stayToken=Math.random()")
            transport_token = crypto.evaluate("window.__stayToken")
            history_requests = crypto.evaluate(
                "window.__quoteFetches.filter(r=>r.url.includes('/klines?')).length"
            )
        assert crypto.evaluate("window.__stayToken") == transport_token, (
            "Asset switch replaced the quote iframe"
        )
        assert (
            crypto.evaluate("window.__quoteFetches.filter(r=>r.url.includes('/klines?')).length")
            == history_requests
        )
        assert crypto.evaluate("window.__quoteSockets.length") == 3
        crypto.wait_for_function(
            "s=>document.body.dataset.asset===s && (window.__quoteSockets.some(w=>w.url.includes(s.toLowerCase()+'@kline_1d')) || window.__subscriptions.filter(x=>x.method==='SUBSCRIBE').at(-1)?.params.includes(s.toLowerCase()+'@kline_1d'))",
            arg=symbol,
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert (
            crypto.evaluate("document.body.scrollHeight")
            <= page.locator("iframe").bounding_box()["height"] + 2
        )
        if code == "BTC":
            page.locator('[data-testid="stMain"]').evaluate("e=>e.scrollTop=0")
            page.screenshot(path=f"/tmp/btc-assets-top-{width}.png")
            page.wait_for_function(
                "()=>document.querySelector('.btc-etf-card strong')?.textContent.includes('+')"
            )
            page.locator(".btc-etf-card").first.evaluate("e=>e.scrollIntoView({block:'center'})")
            page.screenshot(path=f"/tmp/btc-assets-etf-{width}.png")
        payload = page.locator("#btc-live-analysis").evaluate("e=>JSON.parse(e.dataset.seeds)")
        packets = []
        for tf, seed in payload["frames"].items():
            start = seed["end"]
            end = page.evaluate(
                "([t,tf])=>{const d=new Date(t);return tf==='1M'?Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1):t+({'1h':3600000,'4h':14400000,'1d':86400000,'1w':604800000}[tf]);}",
                [start, tf],
            )
            packets.append(
                {
                    "e": "kline",
                    "s": symbol,
                    "E": 0,
                    "k": {
                        "s": symbol,
                        "i": tf,
                        "t": start,
                        "T": end - 1,
                        "o": str(price),
                        "h": str(price * 1.02),
                        "l": str(price * 0.98),
                        "c": str(price),
                        "v": "18",
                        "x": False,
                    },
                }
            )
        crypto.evaluate(
            """({packets,symbol,price})=>{
          window.__assetPrice=price;window.__assetPackets=packets;
          window.__emitAsset=()=>{
            const socket=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance') && s.readyState===1);
            if(!socket)return;
            const now=Date.now();for(const p of packets){p.E=now;p.k.c=String(window.__assetPrice);socket.emit(JSON.stringify({data:p}));}
            socket.emit(JSON.stringify({data:{e:'aggTrade',E:now,s:symbol,p:String(window.__assetPrice)}}));
          };window.__assetTimer=setInterval(window.__emitAsset,500);window.__emitAsset();
        }""",
            {"packets": packets, "symbol": symbol, "price": price},
        )
        page.wait_for_function(
            "()=>[...document.querySelectorAll('#btc-live-analysis article')].every(e=>e.dataset.status==='실시간 · 잠정')"
        )
        page.wait_for_function("p=>window.__assetPlot()?.dataset.livePrice===String(p)", arg=price)
        historical = page.locator(".js-plotly-plot:visible").first.evaluate(
            "p=>({low:Math.min(...p.data[0].close),high:Math.max(...p.data[0].close)})"
        )
        assert price * 0.1 < historical["low"] <= historical["high"] < price * 3, (
            "Live update mixed another coin's history"
        )
        before = page.locator(".js-plotly-plot:visible").first.evaluate("p=>JSON.stringify(p.data)")
        # A BTC candle sent on ETH/SOL/XRP's connection must not be accepted.
        if code != "BTC":
            crypto.evaluate(
                """()=>{const p=JSON.parse(JSON.stringify(window.__assetPackets[2]));p.s=p.k.s='BTCUSDT';p.k.c=String(Number(p.k.c)*1.01);p.E=Date.now()+1;window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')).emit(JSON.stringify({data:p}));}"""
            )
            page.wait_for_timeout(100)
            assert (
                page.locator(".js-plotly-plot:visible").first.evaluate("p=>JSON.stringify(p.data)") == before
            )
        page.get_by_role("tab", name="미래 예측", exact=True).tap()
        page.wait_for_function(
            "s=>window.__assetPlot()?.layout.meta?.btcLive?.symbol===s && window.__assetPlot()?.layout.meta?.btcLive?.kind==='forecast'",
            arg=symbol,
        )
        plot = page.locator(".js-plotly-plot:visible").first
        baseline = event_log.read_text() if event_log else None
        new_price = price * 1.005
        crypto.evaluate("p=>{window.__assetPrice=p;window.__emitAsset();}", new_price)
        page.wait_for_function("p=>window.__assetPlot()?.dataset.livePrice===String(p)", arg=new_price)
        # Independently continue the closed seed through the live forecast path.
        mismatch = plot.evaluate("""p=>{
          const m=p.layout.meta.btcLive,seed=m.indicatorSeed,path=p.data[m.liveIndices[2]].y;
          let count=seed.count,tail=seed.tail.slice(),ema={...seed.ema};
          for(let i=1;i<path.length;i++){count++;tail=[...tail.slice(-19),path[i]];for(const n in ema)ema[n]+=2/(Number(n)+1)*(path[i]-ema[n]);}
          const middle=tail.reduce((s,n)=>s+n,0)/20,width=2*Math.sqrt(tail.reduce((s,n)=>s+(n-middle)**2,0)/20);
          const expected={bb_middle:middle,bb_upper:middle+width,bb_lower:middle-width};
          for(const n in ema)expected['ema_'+n]=count>=Number(n)?ema[n]:null;
          return Object.entries(m.indicatorOverlays).filter(([i,k])=>expected[k]===null?p.data[i].y.at(-1)!==null:Math.abs(p.data[i].y.at(-1)-expected[k])>1e-7);
        }""")
        assert not mismatch, (code, mismatch)
        if baseline is not None:
            assert event_log.read_text() == baseline
        if code == "XRP":
            assert plot.evaluate("p=>p.layout.yaxis.tickformat") == ",.4f"
            assert "1." in page.locator("#btc-live-forecast strong").inner_text()
        region = plot.locator(".nsewdrag").first
        region.scroll_into_view_if_needed()
        box = region.bounding_box()
        x, y = box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.5
        touch(cdp, "touchStart", [(x, y)])
        frozen = plot.evaluate("p=>JSON.stringify(p.data)")
        page.wait_for_timeout(650)
        assert plot.evaluate("p=>JSON.stringify(p.data)") == frozen
        assert any(c.isdigit() for c in plot.locator(".btc-crosshair").text_content())
        touch(cdp, "touchEnd")
        crypto.evaluate("clearInterval(window.__assetTimer)")
        page.wait_for_timeout(650)
        if code == "XRP":
            page.screenshot(path=f"/tmp/btc-assets-xrp-{width}.png")
        last_prices[code] = new_price
        results.append(
            {
                "asset": code,
                "five_live_frames": True,
                "forecast_tick": True,
                "wrong_coin_rejected": True,
                "touch_hold": True,
            }
        )
        fixture.rest = True
    assert not errors, errors
    cleanup(page, crypto)
    context.close()
    return {"width": width, "assets": results, "js_errors": errors}


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
