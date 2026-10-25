from datetime import datetime, timezone

import pytest

from btc_analyzer.data.board_references import parse_won_rates, parse_cnn_mood

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


def test_cnn_uses_published_score_and_rating_without_calculation():
    row = dict(score=32.7, rating="fear", timestamp="2026-10-23T20:00:00Z")
    result = parse_cnn_mood({"fear_and_greed": row}, NOW)
    assert result.score == 32.7 and result.classification == "공포"
    assert result.source == "CNN" and result.url.startswith("https://www.cnn.com/")
    for wrong in (
        {"score": float("nan")},
        {"score": True},
        {"score": 101},
        {"timestamp": "2026-10-25T00:00:00Z"},
        {"timestamp": "2026-01-01T00:00:00Z"},
        {"rating": "invented"},
    ):
        with pytest.raises(ValueError):
            parse_cnn_mood({"fear_and_greed": {**row, **wrong}}, NOW)
