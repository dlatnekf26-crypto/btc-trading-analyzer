"""Exercise the checkout's public UI with production dependencies only, offline."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from streamlit.testing.v1 import AppTest


def main() -> None:
    entry = Path(__file__).resolve().parents[1] / "web_app.py"
    with TemporaryDirectory(prefix="btc-deployment-check-") as directory:
        os.environ["BTC_DEFAULT_SOURCE"] = "demo"
        os.environ["BTC_DEFAULT_EXCHANGE"] = "Upbit"
        os.environ["BTC_WEB_DATA_DIR"] = directory
        app = AppTest.from_file(entry, default_timeout=45).run()
        assert not app.exception, [item.message for item in app.exception]
        assert not app.error, [item.value for item in app.error]
        assert len(app.tabs) == 9 and len(app.metric) == 10
        assert any("현재 접속 세션" in item.value for item in app.info)
        assert any("합성" in item.value for item in app.warning)
        for label in ("백테스트 실행", "모의거래 활성화", "현재 설정 SQLite에 저장"):
            next(button for button in app.button if button.label == label).click().run(timeout=45)
            assert not app.exception, [item.message for item in app.exception]
            assert not app.error, [item.value for item in app.error]
        assert "backtest_result" in app.session_state
        app.session_state["_btc_private_storage"].cleanup()
        print("PASS: public checkout startup, 9 tabs, backtest, paper controls and settings")


if __name__ == "__main__":
    main()
