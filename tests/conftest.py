"""Deterministic market fixtures; unit tests require no exchange network access."""

import numpy as np
import pandas as pd
import pytest
from btc_analyzer.data.service import demo_bundle
from btc_analyzer.analysis.multi_timeframe import prepare
from pathlib import Path
import streamlit as st


@pytest.fixture(scope="session")
def bundle():
    return demo_bundle("1h", bars=500, seed=17)


@pytest.fixture(scope="session")
def features(bundle):
    return prepare(bundle, "1h")


@pytest.fixture
def bars():
    index = pd.date_range("2025-01-01", periods=300, freq="1h", tz="UTC", name="timestamp")
    c = 100 + np.sin(np.arange(300) / 7) * 5 + np.arange(300) * 0.1
    df = pd.DataFrame(
        {"open": c - 0.1, "high": c + 1, "low": c - 1, "close": c, "volume": 100.0}, index=index
    )
    df.attrs["timeframe"] = "1h"
    return df


@pytest.fixture
def offline_dashboard(monkeypatch, tmp_path):
    from scripts.offline_ui_fixture import offline_market_data

    monkeypatch.setenv("BTC_WEB_DATA_DIR", str(tmp_path / "web"))
    st.cache_data.clear()
    with offline_market_data(Path(__file__).resolve().parents[1]):
        yield
    st.cache_data.clear()
