"""Exercise the checkout's public UI with production dependencies only, offline."""

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType

from streamlit.testing.v1 import AppTest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from offline_ui_fixture import offline_market_data  # noqa: E402


def main() -> None:
    entry = Path(__file__).resolve().parents[1] / "web_app.py"
    with TemporaryDirectory(prefix="btc-deployment-check-") as directory, offline_market_data(entry.parent):
        os.environ["BTC_DEFAULT_SOURCE"] = "demo"
        os.environ["BTC_DEFAULT_EXCHANGE"] = "Upbit"  # Old defaults cannot restore removed choices.
        os.environ["BTC_WEB_DATA_DIR"] = directory
        legacy = None
        if os.getenv("BTC_CHECK_STALE_IMPORTS") == "1":
            # Simulate a Cloud process retaining the pre-optimization module.
            # This intentionally lacks candle_boundary; no Git history needed.
            sys.path.insert(0, str(entry.parent / "src"))
            __import__("btc_analyzer")
            legacy = ModuleType("btc_analyzer.candles")
            legacy.__file__ = str(entry.parent / "src/btc_analyzer/candles.py")
            sys.modules[legacy.__name__] = legacy
        app = AppTest.from_file(entry, default_timeout=45).run()
        assert not app.exception, [item.message for item in app.exception]
        assert not app.error, [item.value for item in app.error]
        candle_module = sys.modules["btc_analyzer.candles"]
        assert hasattr(candle_module, "candle_boundary")
        if legacy is not None:
            assert candle_module is not legacy
        assert len(app.tabs) == 4
        assert not any(item.label in ("거래소", "데이터 모드") for item in app.selectbox)
        assert any("BTC/USDT" in item.value for item in app.caption)
        assert not app.warning
        widget = app.get("iframe")[0].proto.srcdoc
        assert "tradingview" not in widget.lower()
        assert any('id="macro-nq"' in item.value and 'id="macro-tnx"' in item.value for item in app.markdown)
        assert any('aria-label="다섯 시간대 방향"' in item.value for item in app.markdown)
        assert "_btc_private_storage" not in app.session_state
        assert not app.sidebar.selectbox and not app.number_input
        decision = next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value)
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run(timeout=45)
        assert not app.exception and not app.error
        assert any('aria-label="예측 요약"' in item.value for item in app.markdown)
        assert not app.get("dataframe") and not app.get("download_button")
        assert any("예측 도착일" in item.value for item in app.caption)
        next(item for item in app.get("button_group") if item.label == "분석 보기").set_value("과거 비교")
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run(timeout=45)
        assert not app.exception and any("예측선이 아닙니다" in item.value for item in app.caption)
        assert len(app.get("plotly_chart")) == 1
        assert next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value) == decision
        next(item for item in app.get("button_group") if item.label == "분석 보기").set_value("예측 경로")
        next(item for item in app.get("button_group") if item.label == "예측 기간").set_value("3mo")
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run(timeout=45)
        assert not app.exception and not app.error
        target = pd.Timestamp.now(tz="UTC").normalize() + pd.DateOffset(months=3)
        assert any(f"예측 도착일 {target:%Y.%m.%d}" in item.value for item in app.caption)
        assert any('aria-label="상승 하락 보합 비교"' in item.value for item in app.markdown)
        next(item for item in app.get("button_group") if item.label == "전망 그래프 보기").set_value("model")
        app.session_state["dashboard_tab"] = "미래 예측"
        app.run(timeout=45)
        assert not app.exception and not app.error
        assert any(item.label == "함께 볼 과거 경로 · 유사도 순" for item in app.get("button_group"))
        assert any("주황색" in item.value for item in app.caption)
        app.session_state["dashboard_tab"] = "시장 개요"
        app.run(timeout=45)
        next(item for item in app.get("button_group") if item.label == "차트 보기").set_value("상세").run(
            timeout=45
        )
        assert not app.exception and not app.error
        control = next(item for item in app.get("button_group") if item.label == "차트 시간대")
        control.set_value("1M").run(timeout=45)
        assert not app.exception and not app.error
        assert any(item.value.startswith("월봉 · ") for item in app.caption)
        for tab in ("기술 지표", "다중 시간대"):
            app.session_state["dashboard_tab"] = tab
            app.run(timeout=45)
            assert not app.exception and not app.error
        assert sys.modules["btc_analyzer.candles"] is candle_module
        assert not (Path(directory) / "sessions").exists()
        print(
            "PASS: public checkout startup, 4 lightweight tabs, Binance BTC/USDT, Ichimoku/detail/monthly charts, medium/long-term signals, forecast/uncertainty/validation and historical analogues; no account storage"
        )
        if legacy is not None:
            print("PASS: retained legacy candles recovered; ordinary reruns preserve module identity")


if __name__ == "__main__":
    main()
