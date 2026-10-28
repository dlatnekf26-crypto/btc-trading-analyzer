"""Browser-local watchlist; selecting a shortcut reuses the existing chart dialog."""

import streamlit as st
from btc_analyzer.assets import MARKETS
from btc_analyzer.ui.browser_assets import browser_asset


def render_quick_access(on_open=None, current=None):
    # Rebind the identical definition to the active runtime after restarts.
    component = st.components.v2.component(
        "market_shortcuts",
        html='<section class="shortcuts" aria-label="내 종목"></section>',
        css=browser_asset("shortcuts.css"),
        js=browser_asset("shortcuts.js"),
    )
    result = component(
        key="shortcuts_detail" if current else "shortcuts_board",
        data={"markets": {code: asset.name for code, asset in MARKETS.items()}, "current": current},
        on_open_change=lambda: None,
    )
    code = result.open
    if on_open and isinstance(code, str) and code in MARKETS:
        on_open(code)
        st.rerun(scope="app")
