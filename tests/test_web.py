"""Verify public visitor isolation and production entry-point behavior."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
import sysconfig

import pytest
from streamlit.testing.v1 import AppTest

from btc_analyzer.config import AppConfig
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.storage.database import Database
from btc_analyzer.ui.web_runtime import ResearchBusy, ResearchGate, runtime_paths


def test_public_checkout_runs_without_project_installation(tmp_path):
    """Disable editable .pth loading while keeping installed third-party libraries."""
    root = Path(__file__).resolve().parents[1]
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
            str(root / "scripts/check_deployment.py"),
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


def test_public_default_live_upbit(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.delenv("BTC_DEFAULT_SOURCE", raising=False)
    monkeypatch.delenv("BTC_DEFAULT_EXCHANGE", raising=False)
    monkeypatch.delenv("BTC_APP_MODE", raising=False)
    captured = {}

    def bundle(self, exchange, symbol, timeframe, start, end, **kwargs):
        captured.update(exchange=exchange, symbol=symbol, cache=self.path, start=start, end=end)
        # Fixture is placed at the requested live boundary; no network calls in tests.
        return demo_bundle(timeframe, 800, end=end, price=130_000_000)

    monkeypatch.setattr(DataService, "bundle", bundle)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=30).run()
    assert not app.exception
    assert not app.error
    assert len(app.tabs) == 9
    assert captured["exchange"] == "Upbit"
    assert captured["symbol"] == "KRW-BTC"
    assert captured["cache"] == tmp_path / "web" / "market-cache.sqlite3"
    assert any("현재 접속 세션" in item.value for item in app.info)
    assert not app.warning


def test_two_public_visitors_do_not_share_accounts_backtests_or_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "demo")
    monkeypatch.setenv("BTC_DEFAULT_EXCHANGE", "Upbit")
    monkeypatch.delenv("BTC_APP_MODE", raising=False)
    private_path = tmp_path / "local-private.sqlite3"
    Database(private_path).save_settings("default", {"private": True})
    monkeypatch.setenv("BTC_DB_PATH", str(private_path))
    entry = Path(__file__).resolve().parents[1] / "web_app.py"
    first = AppTest.from_file(entry, default_timeout=30).run()
    assert not first.exception
    next(b for b in first.button if b.label == "모의거래 활성화").click().run()
    next(b for b in first.button if b.label == "현재 설정 SQLite에 저장").click().run()
    next(b for b in first.button if b.label == "백테스트 실행").click().run(timeout=45)
    assert not first.exception
    first_path = Path(first.session_state["_btc_private_storage"].name) / "analyzer.sqlite3"
    first_db = Database(first_path)
    assert first_db.load_settings("default") is not None
    assert len(first_db.history("backtest_runs")) == 1
    with first_db.connect() as conn:
        first_states = conn.execute("SELECT state FROM paper_accounts").fetchall()
    assert len(first_states) == 1
    assert json.loads(first_states[0][0])["enabled"]
    second = AppTest.from_file(entry, default_timeout=30).run()
    assert not second.exception
    second_path = Path(second.session_state["_btc_private_storage"].name) / "analyzer.sqlite3"
    assert first_path != second_path
    second_db = Database(second_path)
    assert second_db.load_settings("default") is None
    assert second_db.history("backtest_runs").empty
    assert "backtest_result" not in second.session_state
    with second_db.connect() as conn:
        states = conn.execute("SELECT state FROM paper_accounts").fetchall()
    assert all(not json.loads(row[0])["enabled"] for row in states)
    assert Database(private_path).load_settings("default") == {"private": True}
    assert first_db.load_settings("default")["risk"]["capital"] == AppConfig().risk.capital * 1000


def test_public_live_history_limit_prevents_large_download(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "live")
    monkeypatch.setenv("BTC_DEFAULT_EXCHANGE", "Upbit")
    monkeypatch.delenv("BTC_APP_MODE", raising=False)
    calls = []

    def bundle(self, exchange, symbol, timeframe, start, end, **kwargs):
        calls.append(timeframe)
        return demo_bundle(timeframe, 800, end=end)

    monkeypatch.setattr(DataService, "bundle", bundle)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=30).run()
    assert not app.exception
    next(box for box in app.selectbox if box.label == "Timeframe").select("5m")
    today = datetime.now(timezone.utc).date()
    app.date_input[0].set_value((today - timedelta(days=30), today))
    app.run()
    assert not app.exception
    assert any("3,000" in item.value for item in app.info)
    assert calls == ["1h"]
