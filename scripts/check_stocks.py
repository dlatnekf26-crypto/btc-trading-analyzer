"""Stock quotes, units, sessions, chart gestures and forecasts in the real UI."""

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from check_live_widget import MarketFixture, install_quote_transport, send_macro, select_market, cleanup
from check_chart_gestures import gesture_check
from check_touch_charts import inspect

STOCKS = (
    ("SAMSUNG", "삼성전자", "005930.KS", "KRW", 215500),
    ("SKHYNIX", "SK하이닉스", "000660.KS", "KRW", 1272000),
    ("AAPL", "AAPL", "AAPL", "USD", 343.46),
    ("NVDA", "NVDA", "NVDA", "USD", 214.13),
    ("MU", "MU", "MU", "USD", 878.84),
    ("SNDK", "SNDK", "SNDK", "USD", 1299.30),
)
FRAMES = (
    ("5m", "5분"),
    ("15m", "15분"),
    ("1h", "1시간"),
    ("4h", "4시간"),
    ("1d", "일봉"),
    ("1w", "주봉"),
    ("1M", "월봉"),
)
HORIZONS = (
    ("1w", "1주"),
    ("2w", "2주"),
    ("1mo", "1개월"),
    ("2mo", "2개월"),
    ("3mo", "3개월"),
    ("6mo", "6개월"),
)


def verify(browser, width, url, events, all_periods=False, stock_codes=None):
    context = browser.new_context(
        viewport={"width": width, "height": 1000}, has_touch=True, is_mobile=width < 1000
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    install_quote_transport(page)
    MarketFixture(page)
    baseline = events.read_text() if events else None
    page.goto(url)
    page.get_by_role("button", name="삼성전자 차트 열기", exact=True).wait_for(timeout=60000)
    assert page.locator(".board-asset").count() == 12
    assert not page.locator(".js-plotly-plot").count()
    if baseline is not None:
        assert events.read_text() == baseline
    widget = next(frame for frame in page.frames if frame.locator("#binance").count())
    widget.evaluate("""window.__stockToken=Math.random();window.__stockFeed=setInterval(()=>{
      const now=Date.now();window.__quoteSockets.find(s=>s.url.includes('data-stream.binance')&&s.readyState===1)?.emit(JSON.stringify({data:{s:'BTCUSDT',c:'100000',P:'1',E:now}}));
      window.__quoteSockets.find(s=>s.url.includes('upbit')&&s.readyState===1)?.emit(JSON.stringify({code:'KRW-BTC',trade_price:130000000,signed_change_rate:.01,timestamp:now}),true);
    },1000)""")
    token = widget.evaluate("window.__stockToken")
    initial_history = widget.evaluate("window.__quoteFetches.filter(r=>r.url.includes('klines')).length")
    page.screenshot(path=f"/tmp/btc-stocks-board-{width}.png", full_page=True)
    page.get_by_role("button", name="삼성전자 차트 열기", exact=True).tap()
    page.locator("#btc-chart-reader").wait_for(timeout=60000)
    cdp = context.new_cdp_session(page)
    for code, label, symbol, currency, price in STOCKS:
        if stock_codes and code not in stock_codes:
            continue
        if code != "SAMSUNG":
            select_market(page, label)
        page.wait_for_function(
            "s=>document.querySelector('#btc-chart-reader')?.dataset.symbol===s", arg=symbol
        )
        widget.wait_for_function("s=>document.body.dataset.asset===s", arg=symbol)
        page.wait_for_function(
            "s=>document.querySelector('.board-detail')?.dataset.quoteSymbol===s", arg=symbol
        )
        stamp = page.evaluate("Date.now()")
        updated = price + (100 if currency == "KRW" else 0.25)
        send_macro(widget, symbol, updated, stamp, currency=currency)
        expected = f"{updated:,.0f}" if currency == "KRW" else f"{updated:,.2f}"
        page.wait_for_function(
            "p=>document.querySelector('#btc-chart-reader [data-field=current]')?.textContent===p",
            arg=expected,
        )
        assert page.locator("#btc-chart-reader .btc-cursor-reading small").inner_text().strip() == currency
        assert ("₩" if currency == "KRW" else "$") + expected in page.locator(".board-detail").inner_text()
        # Wrong-currency/newer packets cannot replace a valid stock quote.
        send_macro(widget, symbol, 1, stamp + 1000, currency="USD" if currency == "KRW" else "KRW")
        page.wait_for_timeout(100)
        assert page.locator("#btc-chart-reader [data-field=current]").inner_text() == expected
        periods = FRAMES if all_periods else (("1d", "일봉"),)
        for tf, text in periods:
            page.get_by_role("radio", name=text, exact=True).tap()
            page.wait_for_function(
                "v=>{const p=[...document.querySelectorAll('.js-plotly-plot')].find(p=>p.getClientRects().length);return p?.layout?.meta?.btcLive?.symbol===v.s&&p.layout.meta.btcLive.timeframe===v.tf&&p._fullLayout.yaxis4;}",
                arg={"s": symbol, "tf": tf},
            )
            plot = page.locator(".js-plotly-plot:visible").first
            assert plot.locator(".nsewdrag").count() == 4
            assert plot.evaluate(
                "p=>p.data.find(t=>t.type==='candlestick').increasing.line.color==='#ef3f50'"
            )
        if code in ("SAMSUNG", "AAPL"):
            page.get_by_role("radio", name="일봉", exact=True).tap()
            page.wait_for_function(
                "()=>document.querySelector('#btc-chart-reader')?.dataset.timeframe==='1d'"
            )
            page.wait_for_function(
                "s=>{const plots=[...document.querySelectorAll('.js-plotly-plot')].filter(p=>p.getClientRects().length);return plots.length===1&&plots[0].layout?.meta?.btcLive?.symbol===s&&plots[0].layout.meta.btcLive.timeframe==='1d'&&plots[0].querySelectorAll('.nsewdrag').length===4;}",
                arg=symbol,
            )
            plot = page.locator(".js-plotly-plot:visible").first
            gesture_check(page, cdp, plot, events, code)
            inspect(page, cdp, plot, events, code + " scroll")
            page.get_by_role("dialog").evaluate("e=>e.scrollTop=0")
            page.screenshot(path=f"/tmp/btc-stocks-chart-{code}-{width}.png")
        page.get_by_role("tab", name="미래 예측", exact=True).tap()
        withheld = 0
        for _, text in HORIZONS if all_periods else (("1mo", "1개월"),):
            control = page.get_by_role("radio", name=text, exact=True)
            already = control.get_attribute("aria-checked") == "true"
            before = page.locator(".js-plotly-plot:visible").evaluate_all(
                "ps=>ps[0]?.layout?.meta?.btcLive?.center?.length??0"
            )
            control.tap()
            if code == "SNDK" and text in ("2개월", "3개월", "6개월"):
                page.wait_for_function(
                    "()=>!document.querySelector('.js-plotly-plot')&&[...document.querySelectorAll('[data-testid=stAlert]')].some(n=>n.textContent.includes('서로 겹치지 않는 유사 사례가 3개 이상'))"
                )
                assert not page.locator("#btc-forecast-reader").count()
                withheld += 1
                continue
            page.wait_for_function(
                "v=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.getClientRects().length&&p.layout?.meta?.btcLive?.symbol===v.s&&p.layout.meta.btcLive.kind==='forecast'&&(v.same||p.layout.meta.btcLive.center.length!==v.count))",
                arg={"s": symbol, "same": already, "count": before},
            )
            assert page.locator(".btc-direction-card").count() == 3
            assert currency in page.locator("#btc-forecast-reader").inner_text()
        page.get_by_role("tab", name="시장 개요", exact=True).tap()
        page.locator("#btc-chart-reader").wait_for()
        assert widget.evaluate("window.__stockToken") == token
        assert not errors, errors
        print(
            json.dumps(
                {
                    "width": width,
                    "stock": code,
                    "correct_currency": True,
                    "timeframes": len(periods),
                    "forecast_periods_checked": 6 if all_periods else 1,
                    "withheld_for_insufficient_history": withheld,
                }
            ),
            flush=True,
        )
    select_market(page, "BTC")
    page.wait_for_function("()=>document.querySelector('#btc-chart-reader')?.dataset.symbol==='BTCUSDT'")
    assert page.locator("iframe").count() == 1
    assert widget.evaluate("window.__quoteSockets.filter(s=>s.readyState===1).length") == 3
    assert (
        widget.evaluate("window.__quoteFetches.filter(r=>r.url.includes('klines')).length") == initial_history
    )
    page.get_by_role("button", name="Close", exact=True).tap()
    page.get_by_role("dialog").wait_for(state="detached")
    assert page.evaluate("getComputedStyle(document.documentElement).overflow!=='hidden'")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth") and not errors, errors
    widget.evaluate("clearInterval(window.__stockFeed)")
    cleanup(page, widget)
    context.close()
    return {"width": width, "stock_cards": 6, "shared_bridge": True, "crypto_return": True, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--widths", nargs="+", type=int, default=[390, 820, 1440])
    parser.add_argument("--all-periods", action="store_true")
    parser.add_argument("--stocks", nargs="+", choices=[s[0] for s in STOCKS])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for width in args.widths:
            print(
                json.dumps(
                    verify(browser, width, args.app_url, args.event_log, args.all_periods, args.stocks)
                ),
                flush=True,
            )
        browser.close()
