"""Exercise the checkout's public UI with production dependencies only, offline."""

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType

from streamlit.testing.v1 import AppTest


def main() -> None:
    entry = Path(__file__).resolve().parents[1] / "web_app.py"
    with TemporaryDirectory(prefix="btc-deployment-check-") as directory:
        os.environ["BTC_DEFAULT_SOURCE"] = "demo"
        os.environ["BTC_DEFAULT_EXCHANGE"] = "Binance"
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
        assert len(app.tabs) == 10
        assert {item.label for item in app.metric} == {"추세", "모멘텀", "거래량", "변동성", "시장 구조"}
        assert next(item.value for item in app.selectbox if item.label == "거래소") == "Binance"
        assert any(
            "BTC/USDT" in item.value and 'aria-label="시장 가격"' in item.value for item in app.markdown
        )
        assert any("현재 접속 세션" in item.value for item in app.info)
        assert any("합성" in item.value for item in app.warning)
        assert any('aria-label="다섯 시간대 방향"' in item.value for item in app.markdown)
        assert any('aria-label="일목균형표 해석"' in item.value for item in app.markdown)
        decision = next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value)
        app.session_state["dashboard_tab"] = "과거 유사성"
        app.run(timeout=45)
        assert not app.exception and not app.error
        assert any("가장 닮은 과거" in item.value for item in app.success)
        assert any("예측선이 아닙니다" in item.value for item in app.caption)
        assert len(app.get("plotly_chart")) == 1
        assert next(item.value for item in app.markdown if 'aria-label="분석 요약"' in item.value) == decision
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
        for tab, label in (
            ("백테스트", "백테스트 실행"),
            ("모의거래", "모의거래 활성화"),
            ("설정", "현재 설정 SQLite에 저장"),
        ):
            app.session_state["dashboard_tab"] = tab
            app.run(timeout=45)
            next(button for button in app.button if button.label == label).click()
            app.session_state["dashboard_tab"] = tab
            app.run(timeout=45)
            assert not app.exception, [item.message for item in app.exception]
            assert not app.error, [item.value for item in app.error]
        assert "backtest_result" in app.session_state
        assert sys.modules["btc_analyzer.candles"] is candle_module
        app.session_state["_btc_private_storage"].cleanup()
        print(
            "PASS: public checkout startup, Binance BTC/USDT, Ichimoku/detail/monthly charts, medium/long-term signal, historical analogues, 10 lazy tabs, backtest, paper controls and settings"
        )
        if legacy is not None:
            print("PASS: retained legacy candles recovered; ordinary reruns preserve module identity")


if __name__ == "__main__":
    main()
