"""The first price chart must not wait for the multi-frame strategy download."""

from pathlib import Path
import streamlit as st
from scripts.offline_ui_fixture import analysis_app


def test_chart_is_emitted_before_bundle(monkeypatch, offline_dashboard):
    from btc_analyzer.ui import analysis_view

    events = []
    original_chart = st.plotly_chart
    original_bundle = analysis_view.get_live_bundle

    def chart(*a, **kw):
        events.append("chart")
        return original_chart(*a, **kw)

    def bundle(*a, **kw):
        events.append("bundle")
        return original_bundle(*a, **kw)

    bundle.clear = original_bundle.clear
    monkeypatch.setattr(st, "plotly_chart", chart)
    monkeypatch.setattr(analysis_view, "get_live_bundle", bundle)
    app = analysis_app(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=60).run()
    assert not app.exception and not app.error
    assert events.index("chart") < events.index("bundle")
