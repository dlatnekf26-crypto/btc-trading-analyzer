"""Reproducible offline UI timing; separate processes for each checkout."""

import argparse
import cProfile
import json
import os
from pathlib import Path
import statistics
import pstats
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
    parser.add_argument(
        "--settle", type=float, default=0, help="Idle seconds after the cold board, before warm stages (0–10)"
    )
    parser.add_argument("--profile", type=Path, help="Separate diagnostic run; profiling adds overhead")
    args = parser.parse_args()
    args.checkout = args.checkout.resolve()
    if not 1 <= args.repeats <= 30:
        parser.error("repeats must be 1–30")
    if not 0 <= args.settle <= 10:
        parser.error("settle must be 0–10 seconds")
    with TemporaryDirectory(prefix="btc-ui-benchmark-") as directory, offline_market_data(args.checkout):
        os.environ.update(
            BTC_DEFAULT_SOURCE="live",
            BTC_DEFAULT_EXCHANGE="Binance",
            BTC_DB_PATH=str(Path(directory) / "demo.sqlite3"),
            BTC_WEB_DATA_DIR=directory,
        )
        app = AppTest.from_file(args.checkout / "web_app.py", default_timeout=60)
        stages = []
        selected_tab = "시장 개요"
        profiler = cProfile.Profile() if args.profile else None
        if profiler:
            from streamlit.runtime.scriptrunner.script_runner import ScriptRunner

            original = ScriptRunner._run_script

            def profiled(self, *args, **kwargs):
                return profiler.runcall(original, self, *args, **kwargs)

            ScriptRunner._run_script = profiled

        def run(label, action=None):
            start = time.perf_counter()
            if action:
                action()
            states = app._tree.get_widget_states()
            # Streamlit 1.65 AppTest treats stateful tab containers as generic
            # blocks. Send the same string state as the actual browser, including
            # on warm reruns; otherwise AppTest silently returns to tab one.
            for tabs in app.get("tab_container"):
                states.widgets.add(id=tabs.proto.tab_container.id, string_value=selected_tab)
            app._run(widget_state=states)
            elapsed = time.perf_counter() - start
            assert not app.exception, [item.message for item in app.exception]
            assert not app.error, [item.value for item in app.error]
            charts = app.get("plotly_chart")
            stages.append(
                {
                    "stage": label,
                    "seconds": round(elapsed, 4),
                    "chart_bytes": sum(len(item.proto.spec.encode()) for item in charts),
                    "charts": len(charts),
                }
            )
            return elapsed

        def control(label, value):
            return lambda: next(item for item in app.get("button_group") if item.label == label).set_value(
                value
            )

        run("board_first")
        if args.settle:
            time.sleep(args.settle)
        assert not app.get("plotly_chart"), "Quote board performed historical analysis"
        for _ in range(args.repeats):
            run("board_warm")
        run("btc_detail_first", app.button(key="open_BTC").click)
        for _ in range(args.repeats):
            run("btc_detail_warm")
        run("btc_5m_first", control("차트 시간대", "5m"))
        run("btc_1d_return", control("차트 시간대", "1d"))
        selected_tab = "미래 예측"
        run("btc_prediction_first")
        for _ in range(args.repeats):
            run("btc_prediction_warm")
        run("btc_prediction_3mo", control("예측 기간", "3mo"))
        run("btc_comparison_first", control("분석 보기", "과거 비교"))
        app = AppTest.from_file(args.checkout / "web_app.py", default_timeout=60)
        selected_tab = "시장 개요"
        run("aapl_board_prepare")
        run("aapl_detail_first", app.button(key="open_AAPL").click)
        for _ in range(args.repeats):
            run("aapl_detail_warm")
        result = {
            "checkout": str(args.checkout),
            "settle_before_warm_s": args.settle,
            "stages": stages,
            "medians": {
                label: round(statistics.median(row["seconds"] for row in stages if row["stage"] == label), 4)
                for label in dict.fromkeys(row["stage"] for row in stages)
            },
        }
        if profiler:
            ScriptRunner._run_script = original
            profiler.dump_stats(str(args.profile))
            stats = pstats.Stats(profiler)
            result["cpu_top"] = [
                {
                    "function": f"{name[0]}:{name[1]}:{name[2]}",
                    "calls": entry[1],
                    "self_s": round(entry[2], 4),
                    "cumulative_s": round(entry[3], 4),
                }
                for name, entry in sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:35]
            ]
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
