"""Actual forecast UI: conditional controls and a missing external calendar."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from btc_analyzer.data.market_context import FeedState, MarketContext

pytestmark = pytest.mark.usefixtures("offline_dashboard")
ROOT = Path(__file__).resolve().parents[1]


def rerun(app):
    app.session_state["dashboard_tab"] = "미래 예측"
    return app.run()


def plot(app):
    return json.loads(app.get("plotly_chart")[0].proto.spec)


def test_calendar_controls_change_only_conditional_path_and_reset_on_event_change():
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
    rerun(app)
    # The calendar fetch deliberately never blocks the initial render.
    for _ in range(3):
        if any(item.label == "발표 결과를 가정해 보기" for item in app.get("button_group")):
            break
        rerun(app)
    assert not app.exception and not app.error
    original = plot(app)
    next(item for item in app.get("button_group") if item.label == "발표 결과를 가정해 보기").set_value(
        "adverse"
    )
    rerun(app)
    adverse = plot(app)
    assert adverse["data"][:-1] == original["data"]
    assert adverse["data"][-1]["name"] == "발표 조건부 경로"
    next(item for item in app.get("button_group") if item.label == "발표 결과를 가정해 보기").set_value(
        "neutral"
    )
    rerun(app)
    assert plot(app)["data"] == original["data"]
    next(item for item in app.get("button_group") if item.label == "발표 결과를 가정해 보기").set_value(
        "adverse"
    )
    rerun(app)
    selection = next(item for item in app.selectbox if item.label == "주목할 발표")
    selection.select_index(1)
    rerun(app)
    assert app.session_state["release_condition"] == "neutral"
    assert plot(app)["data"] == original["data"]


def test_calendar_failure_preserves_forecast_and_does_not_invent_consensus(monkeypatch):
    from btc_analyzer.ui import correction_view

    class Failed:
        def snapshot(self):
            return MarketContext((FeedState("calendar", error="connection unavailable"),))

    with monkeypatch.context() as patcher:
        patcher.setattr(correction_view, "calendar_service", lambda version: Failed())
        app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
        rerun(app)
        assert not app.exception and not app.error
        assert any("경제 일정·시장 예상치 연결" in item.value for item in app.info)
        assert any('aria-label="조정 시나리오"' in item.value for item in app.markdown)
        assert not any('aria-label="경제지표 발표"' in item.value for item in app.markdown)
        assert all(item.label != "발표 결과를 가정해 보기" for item in app.get("button_group"))
        assert not any(trace["name"] == "발표 조건부 경로" for trace in plot(app)["data"])
