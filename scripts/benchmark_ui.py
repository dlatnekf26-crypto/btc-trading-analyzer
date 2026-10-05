"""Reproducible offline UI timing; separate processes for each checkout."""

import argparse
import json
import os
from pathlib import Path
import statistics
import time
import sys
from tempfile import TemporaryDirectory

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from offline_ui_fixture import offline_market_data  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    args.checkout = args.checkout.resolve()
    if not 1 <= args.repeats <= 30:
        parser.error("repeats must be 1–30")
    with TemporaryDirectory(prefix="btc-ui-benchmark-") as directory, offline_market_data(args.checkout):
        os.environ.update(
            BTC_DEFAULT_SOURCE="live",
            BTC_DEFAULT_EXCHANGE="Binance",
            BTC_DB_PATH=str(Path(directory) / "demo.sqlite3"),
            BTC_WEB_DATA_DIR=directory,
        )
        app = AppTest.from_file(args.checkout / "app.py", default_timeout=60)

        def run(tab=None):
            if tab:
                app.session_state["dashboard_tab"] = tab
            start = time.perf_counter()
            app.run()
            elapsed = time.perf_counter() - start
            assert not app.exception, [item.message for item in app.exception]
            assert not app.error, [item.value for item in app.error]
            return elapsed

        def size():
            return sum(len(item.proto.spec.encode()) for item in app.get("plotly_chart"))

        result = {"checkout": str(args.checkout), "repeats": args.repeats, "cold_main_s": run()}
        result["warm_main_median_s"] = statistics.median(run() for _ in range(args.repeats))
        result["main_chart_bytes"] = size()
        result["first_prediction_s"] = run("미래 예측")
        result["warm_prediction_median_s"] = statistics.median(run("미래 예측") for _ in range(args.repeats))
        result["prediction_chart_bytes"] = size()
        next(item for item in app.get("button_group") if item.label == "분석 보기").set_value("과거 비교")
        result["first_comparison_s"] = run("미래 예측")
        result["comparison_chart_bytes"] = size()
        result = {
            key: round(value, 4) if isinstance(value, float) else value for key, value in result.items()
        }
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
