"""Exchange adapter contract, pagination, malformed/unfinished data and retry behavior."""

import pandas as pd
import pytest
import requests
from btc_analyzer.data.base_provider import normalize, retry, DataError
from btc_analyzer.data.binance_provider import BinanceProvider
from btc_analyzer.data.upbit_provider import UpbitProvider


def test_normalization_quality():
    start = pd.Timestamp("2025-01-01T00:00Z")
    ts = int(start.timestamp() * 1000)
    rows = [
        [ts, 10, 12, 9, 11, 100],
        [ts, 10, 12, 9, 11, 200],
        [ts + 7200000, 11, 12, 10, 11, 100],
        [ts + 10800000, 11, 12, 10, 11, 100],
        [ts + 1234, 10, 12, 9, 11, 100],
        [ts + 3600000, 11, 10, 12, 11, 100],
        ["invalid", 10, 12, 9, 11, 100],
    ]
    result = normalize(rows, "1h", now="2025-01-01T03:30Z")
    assert len(result) == 2
    assert str(result.index.tz) == "UTC"
    assert result.volume.iloc[0] == 200
    assert result.attrs["quality"]["duplicates"] == 1
    assert result.attrs["quality"]["missing_candles"] == 1
    assert result.attrs["quality"]["invalid_rows"] == 3
    assert result.attrs["quality"]["unfinished_rows"] == 1


def test_binance_pagination():
    start = pd.Timestamp("2025-01-01T00:00Z")
    ms = int(start.timestamp() * 1000)
    calls = []

    class Client:
        def fetch_ohlcv(self, symbol, tf, since, limit):
            calls.append(since)
            return [[since + i * 3600000, 10, 12, 9, 11, 100] for i in range(2)]

    result = BinanceProvider(Client()).fetch("BTC/USDT", "1h", start, start + pd.Timedelta(hours=5))
    assert len(result) == 5
    assert calls == [ms, ms + 7200000, ms + 14400000]


def test_upbit_backwards_pagination():
    records = [
        {
            "candle_date_time_utc": f"2025-01-01T0{i}:00:00",
            "opening_price": 10,
            "high_price": 12,
            "low_price": 9,
            "trade_price": 11,
            "candle_acc_trade_volume": 100,
        }
        for i in range(5)
    ]

    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return self.rows

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, params, timeout):
            self.calls.append(params["to"])
            r = Response()
            before = pd.Timestamp(params["to"])
            r.rows = [
                x for x in reversed(records) if pd.Timestamp(x["candle_date_time_utc"], tz="UTC") < before
            ][:2]
            return r

    session = Session()
    result = UpbitProvider(session, delay=0).fetch("KRW-BTC", "1h", "2025-01-01", "2025-01-01T05:00Z")
    assert len(result) == 5
    assert session.calls == ["2025-01-01T05:00:00Z", "2025-01-01T03:00:00Z", "2025-01-01T01:00:00Z"]
    assert result.close.eq(11).all()


def test_retry_bounded_and_recovers():
    calls = []
    waits = []

    def operation():
        calls.append(1)
        if len(calls) < 3:
            raise requests.Timeout("timeout")
        return 123

    assert retry(operation, (requests.Timeout,), sleep=waits.append) == 123
    assert waits == [1, 2]
    with pytest.raises(DataError):
        retry(
            lambda: (_ for _ in ()).throw(requests.Timeout()),
            (requests.Timeout,),
            attempts=2,
            sleep=lambda _: None,
        )


def test_binance_stalled_response():
    class Client:
        def fetch_ohlcv(self, *args, **kwargs):
            return [[0, 10, 12, 9, 11, 100]]

    with pytest.raises(DataError, match="advance"):
        BinanceProvider(Client()).fetch("BTC/USDT", "1h", "2025-01-01", "2025-01-02")


def test_binance_invalid_symbol_is_user_facing_data_error():
    import ccxt

    class Client:
        def fetch_ohlcv(self, *args, **kwargs):
            raise ccxt.BadSymbol("Unsupported market INVALID/USDT")

    with pytest.raises(DataError, match="INVALID/USDT"):
        BinanceProvider(Client()).fetch("INVALID/USDT", "1h", "2025-01-01", "2025-01-02")


def test_binance_region_refusal_is_clear_and_not_retried():
    import ccxt

    class Client:
        calls = 0

        def fetch_ohlcv(self, *args, **kwargs):
            self.calls += 1
            response = requests.Response()
            response.status_code = 451
            try:
                raise requests.HTTPError("Unavailable for legal reasons", response=response)
            except requests.HTTPError as exc:
                raise ccxt.NetworkError("binance GET /api/v3/exchangeInfo") from exc

    client = Client()
    with pytest.raises(DataError, match="HTTP 451"):
        BinanceProvider(client).fetch("BTC/USDT", "1h", "2025-01-01", "2025-01-02")
    assert client.calls == 1


def test_binance_uses_environment_networking_and_keeps_tls_verification():
    provider = BinanceProvider()
    assert provider.client.session.trust_env is True
    assert provider.client.verify is True
    assert provider.client.validateServerSsl is True
