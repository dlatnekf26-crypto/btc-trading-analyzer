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
        item.value for item in app.markdown if 'aria-label="연도별 월간 등락 히트맵"' in item.value
    )
    assert heatmap.count('type="radio"') >= 120 and "2017–" in heatmap
    for _ in range(3):
        sentiment = next(
            item.value for item in app.markdown if 'aria-label="코인 공포탐욕지수"' in item.value
        )
        if 'data-score="32"' in sentiment:
            break
        app.run()
    assert (
        'data-score="32"' in sentiment
        and "Alternative.me" in sentiment
        and "자동 확인 · 일별 지수" in sentiment
    )
    next(item for item in app.get("button_group") if item.label == "히트맵 이력").set_value(5)
    app.run()
    assert not app.exception and not app.error
    changed = next(
        item.value for item in app.markdown if 'aria-label="연도별 월간 등락 히트맵"' in item.value
    )
    assert changed.count('type="radio"') == 72 and changed != heatmap
    assert json.loads(app.get("plotly_chart")[0].proto.spec)["data"] == before["data"]
    assert len(app.get("plotly_chart")) == 1 and len(app.get("iframe")) == 1
    assert not app.get("download_button")

    releases = next(
        item.value for item in app.markdown if 'aria-label="주요 지표 발표와 예상치"' in item.value
    )
    assert "0.3%" in releases and "150K" in releases and "시장 예상" in releases and "이전 발표" in releases
    assert "자주 움직인 시간" not in "".join(item.value for item in app.markdown)
    assert sum(item.value.count('class="btc-pattern-card"') for item in app.markdown) == 1
