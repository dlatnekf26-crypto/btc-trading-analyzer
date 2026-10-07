"""The public market has compact native insights and retains its original chart."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.usefixtures("offline_dashboard")
ROOT = Path(__file__).resolve().parents[1]


def test_sentiment_and_period_heatmap_keep_the_same_market_chart_and_no_extra_iframe():
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=45).run()
    assert not app.exception and not app.error
    before = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(app.get("plotly_chart")) == 1 and len(app.get("iframe")) == 1
    heatmap = next(
        item.value for item in app.markdown if 'aria-label="요일 시간대 등락 히트맵"' in item.value
    )
    assert heatmap.count('type="radio"') == 42 and "최근 30일" in heatmap
    for _ in range(3):
        sentiment = next(
            item.value for item in app.markdown if 'aria-label="코인 공포탐욕지수"' in item.value
        )
        if 'data-score="32"' in sentiment:
            break
        app.run()
    assert 'data-score="32"' in sentiment and "Alternative.me" in sentiment and "일별 갱신" in sentiment
    next(item for item in app.get("button_group") if item.label == "히트맵 기간").set_value(14)
    app.run()
    assert not app.exception and not app.error
    changed = next(
        item.value for item in app.markdown if 'aria-label="요일 시간대 등락 히트맵"' in item.value
    )
    assert "최근 14일" in changed and changed != heatmap
    assert json.loads(app.get("plotly_chart")[0].proto.spec)["data"] == before["data"]
    assert len(app.get("plotly_chart")) == 1 and len(app.get("iframe")) == 1
    assert not app.get("download_button")
