"""New closed candles extend cached public history without downloading it all."""

import pandas as pd
import pytest

from btc_analyzer.candles import candle_close, candle_shift, history_start
from btc_analyzer.data.base_provider import DataError, normalize
from btc_analyzer.data.service import DataService, demo_bundle


@pytest.mark.parametrize(
    "tf,freq,end", [("1d", "D", "2026-10-01"), ("1w", "W-MON", "2026-10-05"), ("1M", "MS", "2026-10-01")]
)
def test_new_boundary_requests_only_overlap_and_new_candle_and_refresh_downloads_all(tmp_path, tf, freq, end):
    end = pd.Timestamp(end, tz="UTC")
    service = DataService(tmp_path / "market.sqlite")
    calls = []

    class Provider:
        def fetch(self, symbol, timeframe, start, until):
            calls.append((start, until))
            index = pd.date_range(start, until, freq=freq, inclusive="left")
            price = 100 if len(calls) == 1 else 101
            return normalize(
                [[int(t.timestamp() * 1000), price, price + 2, price - 2, price, 10] for t in index],
                tf,
                now=until,
            )

    service._providers["Binance"] = Provider()
    original = service.history("Binance", "BTC/USDT", tf, end, 60)
    service.history("Binance", "BTC/USDT", tf, end, 60)
    assert len(calls) == 1
    advanced = candle_shift(end, tf, 1)
    updated = service.history("Binance", "BTC/USDT", tf, advanced, 60)
    assert len(calls) == 2 and calls[1][0] == original.index[-1]
    assert len(updated) == 60 and candle_close(updated.index[-1], tf) == advanced
    assert updated.loc[original.index[-1], "close"] == 101
    assert updated.index.is_unique and updated.attrs["quality"]["missing_candles"] == 0
    service.history("Binance", "BTC/USDT", tf, advanced, 60, refresh=True)
    assert len(calls) == 3 and calls[-1][0] == history_start(advanced, tf, 60)


def test_error_or_missing_latest_is_never_cached_as_updated_history(tmp_path):
    service = DataService(tmp_path / "market.sqlite")
    end = pd.Timestamp("2026-10-01", tz="UTC")

    class Provider:
        fail = False
        missing = False

        def fetch(self, symbol, tf, start, until):
            if self.fail:
                raise DataError("HTTP 451")
            index = pd.date_range(start, until, freq="D", inclusive="left")
            if self.missing:
                index = index[:-1]
            return normalize(
                [[int(t.timestamp() * 1000), 100, 102, 98, 100, 1] for t in index], tf, now=until
            )

    provider = Provider()
    service._providers["Binance"] = provider
    original = service.history("Binance", "BTC/USDT", "1d", end, 60)
    provider.fail = True
    advanced = end + pd.Timedelta(days=1)
    with pytest.raises(DataError, match="451"):
        service.history("Binance", "BTC/USDT", "1d", advanced, 60)
    provider.fail, provider.missing = False, True
    stale = service.history("Binance", "BTC/USDT", "1d", advanced, 60)
    assert candle_close(stale.index[-1], "1d") == end
    unchanged = service.history("Binance", "BTC/USDT", "1d", end, 60)
    pd.testing.assert_frame_equal(original, unchanged)
    provider.missing = False
    repaired = service.history("Binance", "BTC/USDT", "1d", advanced, 60)
    assert candle_close(repaired.index[-1], "1d") == advanced


@pytest.mark.parametrize("base", ["5m", "1d"])
def test_expanded_demo_history_shares_the_exact_dashboard_path(base):
    small = demo_bundle(base, 800, include_macro=True)
    expanded = demo_bundle(base, 800, include_macro=True, history_limits={"1h": 3000}, only_timeframe="1h")
    shared = small["1h"].index.intersection(expanded["1h"].index)
    pd.testing.assert_frame_equal(small["1h"].loc[shared], expanded["1h"].loc[shared])
    assert len(expanded["1h"]) == 3000
    # A caller changing a returned frame cannot corrupt the internal cached path.
    expanded["1h"].iloc[-1, 3] = -1
    fresh = demo_bundle(base, 800, include_macro=True, history_limits={"1h": 3000}, only_timeframe="1h")
    assert fresh["1h"].close.iloc[-1] > 0
