"""One small REST bridge; quote cards do not need repeated native reconstruction."""

from html import escape
import json

import streamlit as st

from btc_analyzer.data.market_context import MacroQuote, SYMBOLS
from btc_analyzer.data.quote_hours import market_hours


def quote_display(value):
    extended = value.extended
    phase, boundary = market_hours(value.symbol)
    return {
        "price": extended.price if extended else value.price,
        "asOf": int((extended.as_of if extended else value.as_of).timestamp() * 1000),
        "change": (extended.price / value.price - 1) * 100
        if extended
        else value.change * 100
        if value.change is not None
        else None,
        "session": extended.session if extended else "regular",
        "marketState": phase,
        "stateUntil": int(boundary.timestamp() * 1000) if boundary else 0,
    }


def snapshot_json(context):
    quotes = []
    for key, symbol in SYMBOLS.items():
        feed = context.feed(key)
        row = {"symbol": symbol, "error": feed.error, "loading": feed.loading}
        value = feed.value
        if isinstance(value, MacroQuote) and value.symbol == symbol:
            row.update(
                **quote_display(value),
                fetched=int(value.fetched_at.timestamp() * 1000),
                regularPrice=value.price,
                regularAsOf=int(value.as_of.timestamp() * 1000),
                regularChange=value.change * 100 if value.change is not None else None,
                delay=value.delay_minutes if value.delay_minutes is not None else -1,
                points=value.points,
                high=value.day_high,
                low=value.day_low,
                volume=value.volume,
            )
        quotes.append(row)
    return json.dumps(quotes, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@st.fragment(run_every=2)
def render_quote_snapshot():
    from btc_analyzer.ui.market_context import current_context

    payload = escape(snapshot_json(current_context()), quote=True)
    st.markdown(
        f'<span hidden id="btc-quote-snapshot" data-quotes="{payload}"></span>', unsafe_allow_html=True
    )
