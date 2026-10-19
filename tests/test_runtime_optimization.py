"""Prevent calendar construction and large immutable metadata copies on UI work."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import pickle
from threading import Event
import time

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.data import quote_hours
from btc_analyzer.data.market_context import MarketContextService, MacroQuote
from btc_analyzer.market_clock import SessionTimes
from btc_analyzer.ui.quote_snapshot import snapshot_json
from btc_analyzer.ui import quote_snapshot


def test_frame_metadata_shares_only_immutable_session_epochs():
    epochs = SessionTimes(np.arange(20000, dtype=np.int64))
    assert deepcopy(epochs) is epochs and not hasattr(epochs, "__dict__")
    assert all(type(value) is int for value in epochs)
    assert pickle.loads(pickle.dumps(epochs)) == epochs
    with pytest.raises(TypeError):
        SessionTimes([[1], 1.2])
    frame = pd.DataFrame({"close": [100.0, 101.0]})
    frame.attrs["bar_starts"] = epochs
    copied = frame.copy(deep=True)
    assert copied.attrs["bar_starts"] is epochs and frame.close.attrs["bar_starts"] is epochs
    copied.iloc[0, 0] = 99
    copied.attrs["bar_starts"] += (20000,)
    assert frame.close.iloc[0] == 100 and len(frame.attrs["bar_starts"]) == 20000


def test_slow_calendar_does_not_hold_quote_publication_snapshot_or_ui_json(monkeypatch):
    now = datetime(2033, 5, 2, 12, tzinfo=timezone.utc)
    started, release = Event(), Event()
    calls = []

    def build(*args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        return ((now + timedelta(hours=1), now + timedelta(hours=7), "regular"),)

    monkeypatch.setattr(quote_hours, "_windows", build)
    monkeypatch.setattr(
        quote_snapshot, "market_hours", lambda symbol: quote_hours.cached_market_hours(symbol, now)
    )
    for symbol in ("AAPL", "NVDA"):
        with quote_hours._lock:
            quote_hours._ready.pop(quote_hours._key(symbol, now), None)
    value = MacroQuote("AAPL", 100.0, now, now, (100.0,), None, 0)
    service = MarketContextService(
        lambda key, at: replace(value, symbol="NVDA" if key == "nvda" else "AAPL"),
        lambda: now,
        keys=("aapl", "nvda"),
        workers=2,
    )
    try:
        service.snapshot()
        assert started.wait(1)
        end = time.monotonic() + 1
        while time.monotonic() < end:
            state = service.snapshot()
            if all(feed.value is not None and not feed.loading for feed in state.feeds):
                break
            time.sleep(0.005)
        else:
            pytest.fail("Calendar construction blocked publication of a completed quote")
        start = time.perf_counter()
        rows = {row["symbol"]: row for row in json.loads(snapshot_json(service.snapshot()))}
        assert time.perf_counter() - start < 0.1
        assert rows["AAPL"]["price"] == rows["NVDA"]["price"] == 100
        assert rows["AAPL"]["marketState"] == "unknown" and len(calls) == 1
    finally:
        release.set()
        service.close()


@pytest.mark.parametrize("mixed", [False, True])
def test_canvas_keeps_price_precision_indices_and_unsupported_svg(mixed):
    from btc_analyzer.ui.canvas_chart import canvas_market

    traces = [
        {"type": "candlestick", "x": [1, 2], "close": [0.000000231234567, 1e9 + 0.125]},
        {"type": "scatter", "x": [1, 2], "y": [None, 0.000000231234567]},
    ]
    if mixed:
        traces.append({"type": "scatter", "mode": "markers", "x": [1, 2], "y": [3.5, 4.5]})
    original = deepcopy(traces)
    spec = canvas_market({"data": traces, "layout": {"meta": {"btcLive": {"overlays": {"1": "rsi"}}}}})
    meta = spec["layout"]["meta"]["btcLive"]
    assert meta["canvasTraces"] == [0, 1] and meta["canvasOnly"] is (not mixed)
    assert meta["overlays"] == {"1": "rsi"}
    assert [{key: value for key, value in row.items() if key != "visible"} for row in traces[:-1]] == original
    assert all(trace["visible"] is False for trace in traces[:2])
    if mixed:
        assert "visible" not in traces[2]
    assert traces[-1]["opacity"] == 0 and traces[-1]["hoverinfo"] == "skip"
