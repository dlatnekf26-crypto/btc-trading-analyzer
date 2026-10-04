"""Exercise the checkout's public UI with production dependencies only, offline."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from streamlit.testing.v1 import AppTest


def main() -> None:
    entry = Path(__file__).resolve().parents[1] / "web_app.py"
    with TemporaryDirectory(prefix="btc-deployment-check-") as directory:
        os.environ["BTC_DEFAULT_SOURCE"] = "demo"
        os.environ["BTC_DEFAULT_EXCHANGE"] = "Binance"
        os.environ["BTC_WEB_DATA_DIR"] = directory
        app = AppTest.from_file(entry, default_timeout=45).run()
        assert not app.exception, [item.message for item in app.exception]
        assert not app.error, [item.value for item in app.error]
        assert len(app.tabs) == 9
        assert {item.label for item in app.metric} == {"추세", "모멘텀", "거래량", "변동성", "시장 구조"}
        assert next(item.value for item in app.selectbox if item.label == "Exchange") == "Binance"
        assert any(
            "BTC/USDT" in item.value and 'aria-label="시장 가격"' in item.value for item in app.markdown
        )
        assert any("현재 접속 세션" in item.value for item in app.info)
        assert any("합성" in item.value for item in app.warning)
        assert any('aria-label="다섯 시간대 방향"' in item.value for item in app.markdown)
        control = next(item for item in app.get("button_group") if item.label == "차트 시간대")
        control.set_value("1M").run(timeout=45)
        assert not app.exception and not app.error
        assert any(item.value.startswith("월봉 · ") for item in app.caption)
        for label in ("백테스트 실행", "모의거래 활성화", "현재 설정 SQLite에 저장"):
            next(button for button in app.button if button.label == label).click().run(timeout=45)
            assert not app.exception, [item.message for item in app.exception]
            assert not app.error, [item.value for item in app.error]
        assert "backtest_result" in app.session_state
        app.session_state["_btc_private_storage"].cleanup()
        print(
            "PASS: public checkout startup, Binance BTC/USDT, five-horizon signal/monthly chart, 9 tabs, backtest, paper controls and settings"
        )


if __name__ == "__main__":
    main()
