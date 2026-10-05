"""Verify public visitor isolation and production entry-point behavior."""

from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import sysconfig

import pytest
from streamlit.testing.v1 import AppTest

from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.storage.database import Database
from btc_analyzer.ui.web_runtime import ResearchBusy, ResearchGate, runtime_paths


def test_public_checkout_runs_without_project_installation(tmp_path):
    """Deploy only Git-tracked files, without the developer's editable install."""
    root = Path(__file__).resolve().parents[1]
    snapshot = tmp_path / "published-source"
    exported = subprocess.run(
        ["git", "checkout-index", "--all", f"--prefix={snapshot}/"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert exported.returncode == 0, exported.stdout + exported.stderr
    program = """
import json
import runpy
import sys
from importlib.util import find_spec
sys.path.extend(json.loads(sys.argv[2]))
assert find_spec('btc_analyzer') is None, 'regression must start without the local project installed'
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    libraries = list({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            program,
            str(snapshot / "scripts/check_deployment.py"),
            json.dumps(libraries),
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: public checkout startup" in result.stdout


def test_private_records_are_separate_and_market_cache_is_shared(tmp_path):
    environ = {"BTC_APP_MODE": "public", "BTC_WEB_DATA_DIR": str(tmp_path / "web")}
    first_state, second_state = {}, {}
    first = runtime_paths(first_state, environ)
    second = runtime_paths(second_state, environ)
    assert first.database != second.database
    assert first.market_cache == second.market_cache
    assert runtime_paths(first_state, environ) == first
    a, b = Database(first.database), Database(second.database)
    a.save_settings("default", {"capital": 12345})
    assert a.load_settings("default") == {"capital": 12345}
    assert b.load_settings("default") is None
    DataService(first.market_cache)
    with sqlite3.connect(first.market_cache) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"market_cache"}
    first_state["_btc_private_storage"].cleanup()
    second_state["_btc_private_storage"].cleanup()
    assert not first.database.exists()


def test_local_database_path_and_existing_state_are_preserved(tmp_path):
    path = tmp_path / "existing.sqlite3"
    Database(path).save_settings("default", {"capital": 9000})
    runtime = runtime_paths({}, {"BTC_DB_PATH": str(path)})
    assert not runtime.public
    assert runtime.database == runtime.market_cache == path
    assert Database(runtime.database).load_settings("default") == {"capital": 9000}


def test_research_gate_is_bounded_and_releases_after_failure():
    gate = ResearchGate()
    with pytest.raises(ValueError, match="calculation failed"):
        with gate.job():
            with pytest.raises(ResearchBusy):
                with gate.job():
                    pytest.fail("second job must not acquire the worker")
            raise ValueError("calculation failed")
    with gate.job():
        pass


@pytest.mark.parametrize("entry", ["app.py", "web_app.py"])
def test_public_default_live_binance_and_usdt_quote(monkeypatch, tmp_path, entry):
    import streamlit as st

    st.cache_data.clear()
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    monkeypatch.setenv("BTC_DEFAULT_EXCHANGE", "Upbit")
    monkeypatch.delenv("BTC_APP_MODE", raising=False)
    captured = {}

    def bundle(self, exchange, symbol, timeframe, start, end, **kwargs):
        captured.update(
            exchange=exchange,
            symbol=symbol,
            cache=self.path,
            start=start,
            end=end,
            include_macro=kwargs.get("include_macro"),
        )
        # Fixture is placed at the requested live boundary; no network calls in tests.
        return demo_bundle(
            timeframe, 800, end=end, price=90_000, include_macro=kwargs.get("include_macro", False)
        )

    monkeypatch.setattr(DataService, "bundle", bundle)
    monkeypatch.setattr(
        "btc_analyzer.data.binance_provider.BinanceProvider.quote",
        lambda self, symbol: {"price": 123456.78, "change_24h": 2.15, "observed_at": "2026-10-04T00:00:00Z"},
    )
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / entry, default_timeout=30).run()
    assert not app.exception
    assert not app.error
    assert len(app.tabs) == 4
    assert captured["exchange"] == "Binance"
    assert captured["symbol"] == "BTC/USDT"
    assert captured["include_macro"] is True
    widget = app.get("iframe")[0].proto.srcdoc
    assert "data-stream.binance.vision" in widget and "api.upbit.com/websocket/v1" in widget
    assert "BTCUSDT" in widget and "ETHUSDT" in widget and "KRW-BTC" in widget
    assert 'id="upbit"' not in widget
    assert 'id="forex"' in widget and 'id="premium"' in widget
    assert 'id="nasdaq"' in widget and 'id="treasury"' in widget
    assert not any(item.label in ("거래소", "데이터 모드") for item in app.selectbox)
    assert captured["cache"] == tmp_path / "web" / "market-cache.sqlite3"
    assert "_btc_private_storage" not in app.session_state
    assert not app.warning


def test_public_visitors_never_read_or_write_existing_private_records(
    monkeypatch, tmp_path, offline_dashboard
):
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    private_path = tmp_path / "local-private.sqlite3"
    database = Database(private_path)
    database.save_settings("default", {"private": True})
    original = private_path.read_bytes()
    monkeypatch.setenv("BTC_DB_PATH", str(private_path))
    entry = Path(__file__).resolve().parents[1] / "web_app.py"
    for _ in range(2):
        app = AppTest.from_file(entry, default_timeout=30).run()
        assert not app.exception and not app.error
        assert "_btc_private_storage" not in app.session_state
        assert "backtest_result" not in app.session_state
        assert len(app.tabs) == 4
    assert private_path.read_bytes() == original
    assert not (tmp_path / "web" / "sessions").exists()


def test_live_analysis_failure_keeps_independent_quote_widget(monkeypatch, tmp_path):
    import streamlit as st
    from btc_analyzer.data.base_provider import DataError

    st.cache_data.clear()
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "live")

    def unavailable(*args, **kwargs):
        raise DataError("Candle API unavailable")

    def no_server_quote(*args, **kwargs):
        raise AssertionError("Browser streaming must not block on a server ticker request")

    monkeypatch.setattr(DataService, "bundle", unavailable)
    monkeypatch.setattr("btc_analyzer.data.binance_provider.BinanceProvider.quote", no_server_quote)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=30).run()
    assert not app.exception
    assert any("Candle API unavailable" in item.value for item in app.error)
    assert len(app.get("iframe")) == 1
    assert "상단 실시간 시세 연결은 독립적으로" in app.info[0].value
    assert not app.get("plotly_chart")
    assert not app.warning


def test_market_hero_escapes_user_supplied_symbols():
    from btc_analyzer.ui.presentation import market_hero

    result = market_hero(
        exchange="Binance",
        symbol='<img src=x onerror="alert(1)">',
        timeframe="1h",
        quote="USDT",
        price=90000,
        change=None,
        change_label="",
        price_label="확정 봉 종가",
        confirmed_at="10.04 15:00",
        demo=True,
    )
    assert "<img" not in result
    assert "&lt;img" in result
    assert "DEMO · 합성 데이터" in result
