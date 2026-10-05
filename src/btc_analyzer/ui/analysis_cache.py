"""Bounded caches for pure market calculations; never cache visitor records."""

import pandas as pd
import streamlit as st

from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS

from btc_analyzer.analysis.multi_timeframe import enrich, prepare
from btc_analyzer.config import AppConfig, IndicatorConfig
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.strategy.composite import composite_signal


@st.cache_data(ttl=3600, max_entries=32, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def feature_frame(raw: pd.DataFrame, timeframe: str, indicators: IndicatorConfig) -> pd.DataFrame:
    """Each actual candle/configuration change invalidates its own feature frame."""
    return enrich(raw, timeframe, AppConfig(indicators=indicators))


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def research_analysis(bundle: dict, timeframe: str, cfg: AppConfig, enriched: dict):
    features = prepare(bundle, timeframe, cfg, enriched=enriched)
    return features, analyze(features, cfg)


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def combined_analysis(bundle: dict, cutoff: pd.Timestamp, cfg: AppConfig, enriched: dict):
    return composite_signal(bundle, cutoff, cfg, enriched=enriched)
