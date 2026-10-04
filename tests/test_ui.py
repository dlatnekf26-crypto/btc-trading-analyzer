"""Exercise the actual Streamlit script and important interactive workflows."""

from pathlib import Path
from streamlit.testing.v1 import AppTest


def press(app, label):
    button = next(b for b in app.button if b.label == label)
    return button.click().run(timeout=45)


def test_dashboard_and_backtest_paper(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "dashboard.sqlite"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert not app.error
    assert len(app.tabs) == 9
    assert {item.label for item in app.metric} == {"추세", "모멘텀", "거래량", "변동성", "시장 구조"}
    assert any('aria-label="분석 요약"' in item.value for item in app.markdown)
    assert any("합성" in x.value for x in app.warning)
    app = press(app, "백테스트 실행")
    assert not app.exception
    assert "backtest_result" in app.session_state
    app = press(app, "Monte Carlo 실행")
    assert not app.exception
    assert "monte_carlo_result" in app.session_state
    app = press(app, "모의거래 활성화")
    assert not app.exception
    app = press(app, "신규 모의거래 중지")
    assert not app.exception
    app = press(app, "현재 설정 SQLite에 저장")
    assert not app.exception
    assert any("저장" in x.value for x in app.success)


def test_live_invalid_binance_symbol_shows_error(monkeypatch, tmp_path):
    import ccxt

    class Client:
        def fetch_ohlcv(self, *args, **kwargs):
            raise ccxt.BadSymbol("Unsupported market INVALID/USDT")

    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "invalid-market.sqlite"))
    monkeypatch.setattr("btc_analyzer.data.binance_provider.ccxt.binance", lambda options: Client())
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    next(x for x in app.selectbox if x.label == "데이터 모드").select("Live · 공개 거래소 데이터")
    app.run()
    assert not app.exception
    assert any("INVALID/USDT" in x.value for x in app.error)


def test_invalid_uploaded_json_shows_validation_error(monkeypatch, tmp_path):
    import io
    import streamlit as st

    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "invalid-config.sqlite"))
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: io.BytesIO(b"[]"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert any("JSON object" in x.value for x in app.error)


def test_corrupt_database_is_preserved_and_explained(monkeypatch, tmp_path):
    path = tmp_path / "corrupt.sqlite"
    original = b"not a SQLite database"
    path.write_bytes(original)
    monkeypatch.setenv("BTC_DB_PATH", str(path))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert any("데이터베이스" in x.value for x in app.error)
    assert path.read_bytes() == original


def test_five_horizon_chart_switch_keeps_composite_decision(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "five-horizon.sqlite"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    original = next(x.value for x in app.markdown if 'aria-label="분석 요약"' in x.value)
    for timeframe, label in (("4h", "4시간"), ("1d", "일봉"), ("1w", "주봉"), ("1M", "월봉")):
        next(x for x in app.get("button_group") if x.label == "차트 시간대").set_value(timeframe).run()
        assert not app.exception and not app.error
        assert next(x.value for x in app.markdown if 'aria-label="분석 요약"' in x.value) == original
        assert any(item.value.startswith(label + " · ") for item in app.caption)
    assert any("월봉 EMA200" in item.value for item in app.caption)
    from btc_analyzer.storage.database import Database

    signals = Database(tmp_path / "five-horizon.sqlite").history("signals")
    assert (signals.timeframe == "ALL").sum() == 1


def test_optional_monthly_failure_keeps_dashboard_but_vetoes_signal(monkeypatch, tmp_path):
    from btc_analyzer.data.service import demo_bundle, DataService

    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "missing-month.sqlite"))
    monkeypatch.setenv("BTC_DEFAULT_SOURCE", "live")

    def missing_month(self, exchange, symbol, tf, start, end, **kwargs):
        bundle = demo_bundle(tf, 800, end=end, include_macro=True)
        bundle["1M"] = bundle["1M"].iloc[:0]
        bundle["1M"].attrs["error"] = "Monthly endpoint temporarily unavailable"
        return bundle

    monkeypatch.setattr(DataService, "bundle", missing_month)
    monkeypatch.setattr(
        "btc_analyzer.data.binance_provider.BinanceProvider.quote",
        lambda self, symbol: {"price": 90000, "change_24h": 0, "observed_at": "2026-10-04T12:00Z"},
    )
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    assert any("관망 · 종합 신호" in item.value for item in app.markdown)
    assert any("Monthly endpoint" in item.value for item in app.markdown)
    next(x for x in app.get("button_group") if x.label == "차트 시간대").set_value("1M").run()
    assert not app.exception and not app.error
    assert any("월봉 데이터를 받지 못했습니다" in item.value for item in app.info)
