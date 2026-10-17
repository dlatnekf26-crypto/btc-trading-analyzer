"""Actual touch pan/pinch/auto, seven timeframes, six horizons and OpenAI boundary.

Run against the development fixture launcher. No market latency/accuracy claim.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport


def touch(cdp, kind, points=()):
    cdp.send(
        "Input.dispatchTouchEvent",
        {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i + 1} for i, (x, y) in enumerate(points)]},
    )


def ranges(plot):
    return plot.evaluate(
        "p=>({x:p._fullLayout.xaxis.range.map(n=>p._fullLayout.xaxis.r2c(n)),y:p._fullLayout.yaxis.range})"
    )


def region_box(page, plot):
    region = plot.locator(".nsewdrag").first
    region.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
    page.wait_for_timeout(80)
    region.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
    box = region.bounding_box()
    assert box and 0 < box["y"] + box["height"] * 0.5 < page.viewport_size["height"], box
    return box


def gesture_check(page, cdp, plot, event_log, label):
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.45
    baseline = event_log.read_text() if event_log else None
    touch(cdp, "touchStart", [(x, y)])
    page.wait_for_timeout(400)
    before = float(plot.get_attribute("data-cursor-price"))
    touch(cdp, "touchMove", [(x + box["width"] * 0.12, y + box["height"] * 0.1)])
    page.wait_for_timeout(80)
    after = float(plot.get_attribute("data-cursor-price"))
    assert before != after, (label, before, after)
    assert any(c.isdigit() for c in plot.locator(".btc-crosshair-time").inner_text())
    assert not any(
        len(word) >= 12 and word.isdigit()
        for word in plot.locator(".btc-crosshair-time").inner_text().split()
    )
    touch(cdp, "touchEnd")
    original = ranges(plot)
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.5
    touch(cdp, "touchStart", [(x, y)])
    touch(cdp, "touchMove", [(x + box["width"] * 0.13, y)])
    touch(cdp, "touchEnd")
    page.wait_for_timeout(160)
    panned = ranges(plot)
    assert panned["x"] != original["x"], (label, "pan", panned, original)
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    distance = min(40, box["width"] * 0.12)
    touch(cdp, "touchStart", [(x - distance, y), (x + distance, y)])
    touch(cdp, "touchMove", [(x - distance * 1.8, y), (x + distance * 1.8, y)])
    touch(cdp, "touchEnd")
    page.wait_for_timeout(180)
    zoomed = ranges(plot)
    assert zoomed["x"][1] - zoomed["x"][0] < (panned["x"][1] - panned["x"][0]) * 0.8, (
        label,
        "pinch",
        zoomed,
        panned,
    )
    # Auto range must enclose only the visible candles, despite distant EMA200.
    fit = plot.evaluate("""p=>{
      const candle=p.data.find(t=>t.type==='candlestick');if(!candle)return true;
      const read=a=>a.bdata?new ({f8:Float64Array,f4:Float32Array}[a.dtype])(Uint8Array.from(atob(a.bdata),c=>c.charCodeAt(0)).buffer):a;
      const axis=p._fullLayout.xaxis,r=axis.range.map(n=>axis.r2c(n)),lo=read(candle.low),hi=read(candle.high);
      const visible=Array.from(candle.x,(x,i)=>[axis.d2c(x),i]).filter(([x])=>r[0]<=x&&x<=r[1]).map(([,i])=>i);
      return visible.every(i=>p._fullLayout.yaxis.range[0]<=lo[i]&&hi[i]<=p._fullLayout.yaxis.range[1]);
    }""")
    assert fit, (label, "auto fit")
    node = page.locator(
        "#btc-forecast-reader"
        if plot.evaluate("p=>p.layout.meta.btcLive.kind==='forecast'")
        else "#btc-chart-reader"
    )
    auto = node.get_by_role("button", name="오토", exact=True)
    auto.tap()
    assert auto.get_attribute("aria-pressed") == "false"
    box = region_box(page, plot)
    x, y = box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.5
    manual = ranges(plot)
    touch(cdp, "touchStart", [(x, y)])
    touch(cdp, "touchMove", [(x + 30, y + 35)])
    touch(cdp, "touchEnd")
    page.wait_for_timeout(160)
    assert ranges(plot)["y"] != manual["y"], (label, "manual Y pan")
    auto.tap()
    assert auto.get_attribute("aria-pressed") == "true"
    if baseline is not None:
        assert event_log.read_text() == baseline, (label, "gesture caused Python analysis")


def verify(browser, width, url, event_log, check_ai=False):
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
    crypto.evaluate("""window.__gestureToken=Math.random();window.__gestureFeed=setInterval(()=>{
      const now=Date.now(),b=window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1);
      for(const [s,c] of [['BTCUSDT','100000'],['ETHUSDT','3000'],['SOLUSDT','150'],['XRPUSDT','1.1532']])b?.emit(JSON.stringify({data:{s,c,P:'2.34',E:now}}));
      window.__quoteSockets.find(s=>s.url.includes('api.upbit.com')&&s.readyState===1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:.01,timestamp:now}),true);
    },1000);""")
    token = crypto.evaluate("window.__gestureToken")
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
            "tf=>document.querySelector('#btc-chart-reader')?.dataset.timeframe===tf&&[...document.querySelectorAll('.js-plotly-plot')].some(p=>p._fullLayout?.meta?.btcLive?.timeframe===tf)",
            arg=tf,
        )
        plot = page.locator(".js-plotly-plot:visible").first
        assert plot.evaluate(
            "p=>['일목 구름','EMA 20','볼린저 밴드'].every(name=>p.data.some(t=>t.name===name))"
        ), tf
        gesture_check(page, cdp, plot, event_log, tf)
        assert not page.get_by_role("button", name="최신 봉", exact=True).count()
        print(json.dumps({"width": width, "timeframe": tf, "pan_pinch_auto": True}), flush=True)
    assert not page.get_by_role("button", name="지표", exact=True).count()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.locator('[data-testid="stMain"]').evaluate("e=>e.scrollTop=0")
    page.screenshot(path=f"/tmp/btc-gestures-top-{width}.png")
    page.get_by_role("tab", name="미래 예측", exact=True).tap()
    for key, label in (
        ("1w", "1주"),
        ("2w", "2주"),
        ("1mo", "1개월"),
        ("2mo", "2개월"),
        ("3mo", "3개월"),
        ("6mo", "6개월"),
    ):
        page.get_by_role("radio", name=label, exact=True).tap()
        page.wait_for_function(
            "()=>document.querySelector('#btc-forecast-reader')&&[...document.querySelectorAll('.js-plotly-plot')].some(p=>p._fullLayout?.meta?.btcLive?.kind==='forecast')"
        )
        page.wait_for_timeout(180)
        assert not page.locator('[data-testid="stException"]').count()
    plot = page.locator(".js-plotly-plot:visible").first
    gesture_check(page, cdp, plot, event_log, "forecast")
    if check_ai:
        original = plot.evaluate("p=>JSON.stringify(p.data.filter(t=>t.meta?.direction).map(t=>t.y))")
        page.get_by_role("button", name="AI로 가격대 분석", exact=True).tap()
        page.locator(".btc-ai-card").wait_for(timeout=30000)
        page.wait_for_function(
            "()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.data?.filter(t=>t.meta?.btcAI).length===3)"
        )
        assert plot.evaluate("p=>JSON.stringify(p.data.filter(t=>t.meta?.direction).map(t=>t.y))") == original
        assert page.locator(".btc-ai-card").inner_text().count("개발 검사") == 1
        plot.scroll_into_view_if_needed()
        page.screenshot(path=f"/tmp/btc-gestures-ai-{width}.png")
    assert (
        crypto.evaluate("window.__gestureToken") == token
        and crypto.evaluate("window.__quoteSockets.length") == 3
    )
    assert page.locator("iframe").count() == 1 and not errors, errors
    crypto.evaluate("clearInterval(window.__gestureFeed)")
    cleanup(page, crypto)
    context.close()
    return {
        "width": width,
        "seven_frames": True,
        "six_horizons": True,
        "AI_boundary": check_ai,
        "js_errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument(
        "--check-ai",
        action="store_true",
        help="Exercise the AI provider explicitly; use the development fixture.",
    )
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in (390, 820, 1440):
            try:
                print(
                    json.dumps(verify(browser, width, args.app_url, args.event_log, check_ai=args.check_ai)),
                    flush=True,
                )
            except Exception:
                for ctx in browser.contexts:
                    for page in ctx.pages:
                        page.screenshot(path=f"/tmp/btc-gestures-failed-{width}.png")
                        Path(f"/tmp/btc-gestures-failed-{width}.txt").write_text(
                            page.locator("body").inner_text()
                        )
                raise
        browser.close()
