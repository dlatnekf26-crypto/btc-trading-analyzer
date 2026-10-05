"""Exercise the actual Streamlit script and important interactive workflows."""

from pathlib import Path
from streamlit.testing.v1 import AppTest
import pytest

pytestmark = pytest.mark.usefixtures("offline_dashboard")


def test_dashboard_only_has_requested_views_and_never_opens_account_db(monkeypatch, tmp_path):
    from btc_analyzer.storage.database import Database

    path = tmp_path / "dashboard.sqlite"
    monkeypatch.setenv("BTC_DB_PATH", str(path))

    def forbidden(*args, **kwargs):
        raise AssertionError("The lightweight dashboard must not initialize an account database")

    monkeypatch.setattr(Database, "__init__", forbidden)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    assert [tab.label for tab in app.tabs] == ["시장 개요", "기술 지표", "다중 시간대", "미래 예측"]
    assert any('aria-label="분석 요약"' in item.value for item in app.markdown)
    assert not app.warning
    assert not any(x.label in ("거래소", "데이터 모드") for x in app.selectbox)
    assert len(app.get("iframe")) == 1
    assert not app.sidebar.selectbox and not app.number_input and not app.file_uploader
    for tab in ["기술 지표", "다중 시간대", "미래 예측"]:
        app.session_state["dashboard_tab"] = tab
        app.run()
        assert not app.exception and not app.error
    assert not path.exists()


def test_live_invalid_binance_symbol_shows_error(monkeypatch, tmp_path):
    import ccxt

    class Client:
        def fetch_ohlcv(self, *args, **kwargs):
            raise ccxt.BadSymbol("Unsupported market INVALID/USDT")

    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "invalid-market.sqlite"))
    monkeypatch.setattr("btc_analyzer.data.binance_provider.ccxt.binance", lambda options: Client())
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert any("INVALID/USDT" in x.value for x in app.error)


def test_removed_tab_state_recovers_and_existing_database_is_untouched(monkeypatch, tmp_path):
    path = tmp_path / "existing.sqlite"
    original = b"do not open or replace an existing research database in Live"
    path.write_bytes(original)
    monkeypatch.setenv("BTC_DB_PATH", str(path))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    app.session_state["dashboard_tab"] = "모의거래"
    app.run()
    assert not app.exception and not app.error
    assert app.session_state["dashboard_tab"] == "시장 개요"
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
    app.session_state["dashboard_tab"] = "다중 시간대"
    app.run()
    assert any("월봉 EMA200" in item.value for item in app.caption)
    assert not (tmp_path / "five-horizon.sqlite").exists()


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


def test_ichimoku_view_and_overlay_controls_preserve_signal(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_DB_PATH", str(tmp_path / "ichimoku-ui.sqlite"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    summary = next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value)
    assert not any("일목균형표, 이렇게 읽어요" in item.value for item in app.subheader)
    assert any("미래 가격 예측이 아닙니다" in item.value for item in app.caption)
    next(item for item in app.get("button_group") if item.label == "차트 보기").set_value("상세").run()
    assert not app.exception and not app.error
    assert any(item.label == "표시할 봉 수" for item in app.select_slider)
    assert all(
        "가격 영역" not in option.content
        for item in app.get("button_group")
        if item.label == "겹쳐 볼 지표"
        for option in item.proto.options
    )
    next(item for item in app.get("button_group") if item.label == "겹쳐 볼 지표").set_value(
        ["일목균형표", "이동평균선", "볼린저밴드"]
    ).run()
    assert not app.exception and not app.error
    next(item for item in app.get("button_group") if item.label == "겹쳐 볼 지표").set_value([]).run()
    assert not app.exception and not app.error
    assert next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value) == summary
