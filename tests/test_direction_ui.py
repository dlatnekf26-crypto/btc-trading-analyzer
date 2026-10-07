"""Public forecast default, comparison/model switching and independent what-ifs."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.usefixtures("offline_dashboard")
ROOT = Path(__file__).resolve().parents[1]


def rerun(app):
    app.session_state["dashboard_tab"] = "미래 예측"
    return app.run()


def chart(app):
    return json.loads(app.get("plotly_chart")[0].proto.spec)


def control(app, label):
    return next(item for item in app.get("button_group") if item.label == label)


def test_default_compares_three_directions_and_model_switch_keeps_original_forecast():
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
    rerun(app)
    assert not app.exception and not app.error
    assert len(app.get("plotly_chart")) == 1
    before = chart(app)
    assert len(before["data"]) == 6
    assert [trace["meta"]["direction"] for trace in before["data"][3:]] == ["up", "flat", "down"]
    cards = next(item.value for item in app.markdown if 'aria-label="상승 하락 보합 비교"' in item.value)
    assert cards.count("data-direction=") == 3
    assert any("미래 확률이 아니에요" in item.value for item in app.caption)
    assert not any(item.label == "함께 볼 과거 경로 · 유사도 순" for item in app.get("button_group"))
    control(app, "전망 그래프 보기").set_value("model")
    rerun(app)
    model = chart(app)
    assert model["data"][3]["name"] == "예상 중심 경로" and model["data"][4]["name"] == "과거 사례 재현"
    control(app, "함께 볼 과거 경로 · 유사도 순").set_value(1)
    rerun(app)
    changed = chart(app)
    assert changed["data"][:4] == model["data"][:4]
    assert changed["data"][4]["y"] != model["data"][4]["y"]
    control(app, "전망 그래프 보기").set_value("comparison")
    rerun(app)
    assert chart(app)["data"] == before["data"]
    assert not app.get("download_button")


def test_release_assumption_does_not_change_direction_ranking_or_branch_prices():
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
    rerun(app)
    for _ in range(3):
        if any(item.label == "발표 결과를 가정해 보기" for item in app.get("button_group")):
            break
        rerun(app)
    base = chart(app)
    cards = next(item.value for item in app.markdown if 'aria-label="상승 하락 보합 비교"' in item.value)
    control(app, "발표 결과를 가정해 보기").set_value("adverse")
    rerun(app)
    assert not app.exception and not app.error
    adverse = chart(app)
    assert adverse["data"][:-1] == base["data"]
    assert adverse["data"][-1]["name"] == "발표 조건부 경로"
    assert (
        next(item.value for item in app.markdown if 'aria-label="상승 하락 보합 비교"' in item.value) == cards
    )
    control(app, "발표 결과를 가정해 보기").set_value("neutral")
    rerun(app)
    assert chart(app)["data"] == base["data"]
