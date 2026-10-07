"""Compare chronological forecast errors on locally saved public OHLCV CSV data.

CSV needs a UTC timestamp index and open, high, low, close, volume columns.
No parameters are fitted by this script; it reports every supported horizon.
"""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from btc_analyzer.analysis.forecast import HORIZON_LABELS, horizon_days, predict_history  # noqa: E402


def evaluate(frame, *, use_technical=True):
    end = frame.index[-1] + pd.Timedelta(days=1)
    rows = []
    for horizon in HORIZON_LABELS:
        days = horizon_days(end, horizon)
        start = perf_counter()
        base = predict_history(frame, "1d", end, 30, days, use_context=False)
        adaptive = predict_history(
            frame, "1d", end, 30, days, use_context=not use_technical, use_technical=use_technical
        )
        rows.append(
            {
                "horizon": horizon,
                "days": days,
                "validation_cases": len(adaptive.validation),
                "pattern_mae_pp": None if base.mae is None else base.mae * 100,
                "adaptive_mae_pp": None if adaptive.mae is None else adaptive.mae * 100,
                "no_change_mae_pp": None if adaptive.baseline_mae is None else adaptive.baseline_mae * 100,
                "context_pairs": adaptive.context_cases,
                "current_selection": adaptive.model,
                "validation_context_uses": sum(c.model == "context" for c in adaptive.validation),
                "validation_technical_uses": sum(c.model == "technical" for c in adaptive.validation),
                "pattern_price": None if base.prediction is None else base.prediction.center[-1],
                "adaptive_price": None if adaptive.prediction is None else adaptive.prediction.center[-1],
                "indicator_reason": adaptive.technical.reason if adaptive.technical else None,
                "gate_pattern_mae_pp": adaptive.pattern_mae * 100
                if adaptive.pattern_mae is not None
                else None,
                "gate_candidate_mae_pp": adaptive.context_mae * 100
                if adaptive.context_mae is not None
                else None,
                "paired_seconds": perf_counter() - start,
            }
        )
    return {
        "start": str(frame.index[0]),
        "closed_until": str(end),
        "bars": len(frame),
        "candidate": "five_indicator_families" if use_technical else "legacy_rsi_adx_cmf",
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument(
        "--legacy-context", action="store_true", help="Reproduce the earlier RSI/ADX/CMF research candidate"
    )
    args = parser.parse_args()
    frame = pd.read_csv(args.csv, index_col=0, parse_dates=True).sort_index()
    frame.index = pd.to_datetime(frame.index, utc=True)
    print(json.dumps(evaluate(frame, use_technical=not args.legacy_context), indent=2))


if __name__ == "__main__":
    main()
