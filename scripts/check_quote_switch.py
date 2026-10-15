"""Count Canvas work and verify live subscription changes without reconnects.

Controlled exchange packets exercise the real widget, not internet latency.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from benchmark_macro_updates import archived
from check_live_widget import MarketFixture, cleanup, install_quote_transport, send, widget_html


def open_widget(browser, source):
    page = browser.new_page(viewport={"width": 390, "height": 1000})
    page.clock.install(time=datetime(2026, 10, 15, 12, 0, 10, tzinfo=timezone.utc))
    install_quote_transport(page)
    fixture = MarketFixture(page)
    source = source.replace(
        '<div class="dashboard">',
        '<span hidden id="btc-live-selection" data-symbol="BTCUSDT"></span><div class="dashboard">',
    )
    page.route("http://widget.test/", lambda r: r.fulfill(body=source, content_type="text/html"))
    page.goto("http://widget.test/")
    page.locator('#binance[data-history="ready"]').wait_for()
    send(page.main_frame, "BTCUSDT", 100000, page.evaluate("Date.now()"))
    page.clock.run_for(100)
    fixture.rest = False
    return page


def canvas_work(browser, source):
    page = open_widget(browser, source)
    page.evaluate("""()=>{
      window.__draws=0;const canvas=document.querySelector('#binance canvas');
      const ctx=canvas.getContext('2d'),original=ctx.clearRect;
      ctx.clearRect=function(...args){window.__draws++;return original.apply(this,args);};
    }""")
    for _ in range(100):
        send(page.main_frame, "BTCUSDT", 100000, page.evaluate("Date.now()"))
        page.clock.run_for(100)
    unchanged = page.evaluate("window.__draws")
    send(page.main_frame, "BTCUSDT", 100001, page.evaluate("Date.now()"))
    page.clock.run_for(100)
    assert page.locator("#binance .price span").inner_text() == "100,001.00"
    changed = page.evaluate("window.__draws") - unchanged
    assert changed == 1, (unchanged, changed)
    # A new minute is a new point even if its price is unchanged.
    page.clock.set_system_time(
        datetime.fromtimestamp((page.evaluate("Date.now()") + 60000) / 1000, timezone.utc)
    )
    before = page.evaluate("window.__draws")
    send(page.main_frame, "BTCUSDT", 100001, page.evaluate("Date.now()"))
    page.clock.run_for(100)
    assert page.evaluate("window.__draws") > before, (before, page.evaluate("window.__draws"))
    cleanup(page, page.main_frame)
    return {"unchanged_ticks": 100, "unchanged_draws": unchanged, "changed_draws": changed}


def switching(browser):
    page = open_widget(browser, widget_html())
    page.evaluate(
        "window.__originalSockets=window.__quoteSockets.slice();window.__savedCanvas=document.querySelector('#binance canvas')"
    )
    page.evaluate("""()=>{
      window.__controlTimes=[];
      for(const socket of window.__quoteSockets){const send=socket.send;socket.send=function(raw){
        if(JSON.parse(raw).method)window.__controlTimes.push(Date.now());return send.call(this,raw);
      };}
    }""")
    initial_requests = page.evaluate("window.__quoteFetches.length")
    previous = "BTCUSDT"
    for code in ("ETH", "SOL", "XRP", "BTC", "ETH", "XRP"):
        symbol = code + "USDT"
        page.evaluate(
            "s=>{document.querySelector('#btc-live-selection').dataset.symbol=s;}",
            symbol,
        )
        page.clock.run_for(100)
        assert page.locator("body").get_attribute("data-asset") == symbol
        page.clock.run_for(700)
        commands = page.evaluate("window.__subscriptions.filter(s=>s.method)")[-2:]
        assert [c["method"] for c in commands] == ["UNSUBSCRIBE", "SUBSCRIBE"]
        for command, expected in zip(commands, (previous, symbol)):
            assert command["params"] == [
                expected.lower() + "@kline_" + tf for tf in ("1h", "4h", "1d", "1w", "1M")
            ]
        assert page.evaluate(
            "window.__quoteSockets.length===3 && window.__quoteSockets.every((s,i)=>s===window.__originalSockets[i] && s.readyState===1)"
        )
        assert page.evaluate("document.querySelector('#binance canvas')===window.__savedCanvas")
        previous = symbol
    assert page.evaluate("window.__quoteFetches.length") == initial_requests
    ids = page.evaluate("window.__subscriptions.filter(s=>s.method).map(s=>s.id)")
    assert len(ids) == len(set(ids))
    # Fast taps coalesce into the latest choice while quotes stay connected.
    prior = page.evaluate("window.__subscriptions.filter(s=>s.method).length")
    for code in ("ETH", "SOL", "BTC", "XRP"):
        page.evaluate(
            "s=>{const n=document.querySelector('#btc-live-selection');n.replaceWith(Object.assign(n.cloneNode(),{id:'btc-live-selection'}));document.querySelector('#btc-live-selection').dataset.symbol=s;}",
            code + "USDT",
        )
        page.clock.run_for(25)
    page.clock.run_for(900)
    commands = page.evaluate("window.__subscriptions.filter(s=>s.method)")
    assert len(commands) - prior <= 4
    assert commands[-1]["params"][0].startswith("xrpusdt@")
    times = page.evaluate("window.__controlTimes")
    assert all(sum(0 <= t - start < 1000 for t in times) <= 4 for start in times)
    # A quiet individual symbol must not close the shared connection while
    # another symbol keeps delivering trades. Per-symbol REST fallback remains.
    for _ in range(140):
        send(page.main_frame, "XRPUSDT", 1.1532, page.evaluate("Date.now()"))
        page.clock.run_for(100)
    assert page.evaluate("window.__quoteSockets.length") == 3
    page.evaluate(
        "document.querySelector('#btc-live-selection').replaceWith(Object.assign(document.createElement('span'),{id:'btc-live-selection'}))"
    )
    page.clock.run_for(100)
    assert page.locator("body").get_attribute("data-asset") == "XRPUSDT"
    # Reconnect uses the latest selected market, never the initial BTC candles.
    page.evaluate("window.__originalSockets.find(s=>s.url.includes('data-stream.binance')).close()")
    page.clock.run_for(2500)
    socket_url = page.evaluate(
        "window.__quoteSockets.filter(s=>s.url.includes('data-stream.binance')).at(-1).url"
    )
    assert "xrpusdt@kline_1d" in socket_url and "btcusdt@kline_1d" not in socket_url
    cleanup(page, page.main_frame)
    return {
        "switches": 6,
        "additional_connections": 0,
        "additional_history_requests": 0,
        "selected_market_reconnect": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-widget", type=Path)
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        result = {"switching": switching(browser), "after": canvas_work(browser, widget_html())}
        assert result["after"]["unchanged_draws"] == 0
        if args.before_widget:
            # This benchmark needs only price parsing; the archived bridge's
            # placeholder is a comment and there is no parent model/chart.
            before = archived(args.before_widget).replace(
                "/* LIVE_ANALYSIS_BRIDGE */",
                "const liveAnalysis={paint(){},accept(){},stop(){},dispose(){}};",
            )
            result["before"] = canvas_work(browser, before)
            assert result["before"]["unchanged_draws"] >= 90
        browser.close()
    print(json.dumps(result))
