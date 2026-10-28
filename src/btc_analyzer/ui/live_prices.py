"""Browser-owned public quotes: no keys, Python polling, or chart dependencies."""

import json

from btc_analyzer.ui.browser_assets import quotes_document, browser_asset

import streamlit as st
import streamlit.components.v1 as components
from btc_analyzer.assets import ASSETS, MARKETS, SESSION_MARKETS, EXCHANGE_HISTORY

LIVE_ANALYSIS_CSS = "<style>" + browser_asset("live-analysis.css") + "</style>"

LIVE_PRICES_HTML = quotes_document()


def live_prices_html(asset_code="BTC", *, bridge_only=False):
    if asset_code not in MARKETS:
        raise ValueError("Unsupported live asset")
    markets = json.dumps(
        [[a.code, a.card_id, a.name, a.decimals] for a in ASSETS.values()], ensure_ascii=False
    )
    default_markets = "[['BTC','binance','비트코인',2],['ETH','ethereum','이더리움',2],['SOL','solana','솔라나',2],['XRP','ripple','리플',4]]"
    sessions = json.dumps(
        [
            [
                code,
                a.symbol,
                a.card_id.removeprefix("macro-"),
                EXCHANGE_HISTORY[code].unit,
                EXCHANGE_HISTORY[code].currency,
                a.decimals,
            ]
            for code, a in SESSION_MARKETS.items()
        ],
        ensure_ascii=False,
    )
    default_sessions = "[['NQ','NQ=F','nq','pt','USD',2],['KOSPI','^KS11','kospi','pt','KRW',2]]"
    document = LIVE_PRICES_HTML.replace(default_markets, markets).replace(default_sessions, sessions)
    if bridge_only:
        document = document.replace("<body>", '<body data-bridge-only="true">').replace(
            "</style>",
            "body[data-bridge-only]{margin:0;height:0;overflow:hidden}body[data-bridge-only] .dashboard{display:none}</style>",
        )
    return document


def render_live_prices(asset_code="BTC") -> None:
    """Keep quotes/history connected across tabs and asset changes."""
    st.markdown(
        f'<span hidden id="btc-live-selection" data-symbol="{MARKETS[asset_code].stream_symbol}"></span>',
        unsafe_allow_html=True,
    )
    components.html(live_prices_html(asset_code, bridge_only=True), height=0, scrolling=False)
    st.markdown(LIVE_ANALYSIS_CSS, unsafe_allow_html=True)
    st.markdown(
        """<style>
#btc-move-alerts[hidden]{display:none}#btc-move-alerts{display:grid;gap:10px;margin:0 0 12px}
[data-testid="stElementContainer"]:has(#btc-move-alerts[hidden]){display:none}
[data-testid="stElementContainer"]:has(#btc-live-selection){display:none}
iframe[data-testid="stIFrame"][srcdoc]{display:block}
[data-testid="stElementContainer"]:has(> iframe[data-testid="stIFrame"][srcdoc]){height:auto!important;min-height:0!important;max-height:none!important;flex:0 0 auto!important}
.btc-move-card{border:1px solid #e7eaf2;border-left:4px solid #ce4260;background:#fff;border-radius:16px;padding:14px 16px;overflow-wrap:anywhere}
.btc-move-card.up{border-left-color:#0a996e}.btc-move-card strong{font-size:16px;color:#192434}
.btc-move-card p{font-size:13px;color:#59677c;line-height:1.5;margin:6px 0}
.btc-move-card a{font-size:14px;font-weight:600;color:#3182f6;display:block;padding:4px 0;touch-action:manipulation}
.btc-move-card .btc-move-meta{font-size:11px;color:#7b8798}
</style><section hidden id="btc-move-alerts" aria-label="실시간 급등락과 관련 소식" aria-live="polite"></section>""",
        unsafe_allow_html=True,
    )
