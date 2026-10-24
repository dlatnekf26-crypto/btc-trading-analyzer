from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from btc_analyzer.data.board_references import parse_won_rates, stock_mood

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_yen_is_per_100_and_euro_per_one_with_strict_dates():
    payload = dict(base="EUR", amount=1, date="2026-10-23", rates={"KRW": 1600, "JPY": 160})
    rates = parse_won_rates(payload, NOW)
    assert rates.yen100 == 1000 and rates.euro == 1600
    for wrong in (
        {"base": "USD"},
        {"date": "2026-10-25"},
        {"date": "2026-10-01"},
        {"rates": {"KRW": True, "JPY": 160}},
        {"rates": {"KRW": 1600, "JPY": 0}},
    ):
        with pytest.raises(ValueError):
            parse_won_rates({**payload, **wrong}, NOW)


def test_stock_mood_direction_flat_and_insufficient_history():
    index = pd.date_range("2026-01-01", periods=200, tz="UTC")

    def mood(values):
        frame = pd.DataFrame({"close": values}, index=index)
        return stock_mood(frame).score

    assert mood(np.linspace(100, 150, 200)) > 70
    assert mood(np.linspace(150, 100, 200)) < 30
    assert mood(np.ones(200) * 100) == 50
    with pytest.raises(ValueError):
        stock_mood(pd.DataFrame({"close": [100]}))
