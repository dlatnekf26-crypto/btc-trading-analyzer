"""The landing page is quote-only; card actions and public links load analysis."""

from pathlib import Path
import json
import shutil
import subprocess

import pytest
from streamlit.testing.v1 import AppTest
from btc_analyzer.ui.browser_assets import browser_asset

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("offline_dashboard")


def test_landing_never_collects_candles_or_forecasts(monkeypatch):
    from btc_analyzer.data.service import DataService
    from btc_analyzer.ui import exchange_view, history_view

    def unexpected(*args, **kwargs):
        pytest.fail("Opening the quote board must not collect or analyze history")

    monkeypatch.setattr(DataService, "bundle", unexpected)
    monkeypatch.setattr(DataService, "history", unexpected)
    monkeypatch.setattr(exchange_view, "market_response", unexpected)
    monkeypatch.setattr(history_view, "forecast_analysis", unexpected)
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    assert len(app.get("iframe")) == 1
    assert not app.tabs and not app.get("plotly_chart")
    from btc_analyzer.assets import MARKETS

    assert {button.key for button in app.button} == {"open_" + code for code in MARKETS}
    app.run()
    assert not app.exception and not app.get("plotly_chart")


@pytest.mark.parametrize("market", ["BTC", "ETH", "SOL", "XRP", "NQ", "KOSPI"])
def test_market_card_opens_the_matching_detail(market):
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=45).run()
    app.button(key="open_" + market).click().run()
    assert not app.exception and not app.error and not app.warning
    assert app.session_state["analysis_asset"] == market
    assert dict(app.query_params) == {"market": market, "view": "chart"}
    assert len(app.get("plotly_chart")) == 1 and len(app.tabs) == 2
    # The modal shares quote state instead of duplicating macro IDs/streams.
    for key in ("nq", "kospi", "oil", "tnx", "tyx"):
        assert sum(item.value.count(f'id="macro-{key}"') for item in app.markdown) == 1
    control = next(item for item in app.selectbox if item.label == "분석할 시장")
    control.set_value("ETH").run()
    assert not app.exception and app.query_params["market"] == "ETH"


@pytest.mark.parametrize("market,view", [("unknown", "chart"), ("BTC", "unknown")])
def test_invalid_deep_link_stays_on_the_quote_board(market, view):
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30)
    app.query_params.update({"market": market, "view": view})
    app.run()
    assert not app.exception and not app.get("plotly_chart")


def test_ticker_metrics_keep_valid_stats_on_trade_and_bad_packets():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is a development-only check")
    program = (
        "const validNumber=n=>typeof n==='number'&&Number.isFinite(n);"
        + browser_asset("board-quotes.js")
        + """
const s={market:'binance'};
tickerMetrics(s,{h:'105',l:'95',v:'12',q:'1200'});
const before=JSON.stringify(s.metrics);
for(const item of [{e:'aggTrade',p:'101'}, {h:'90',l:'95',v:'12',q:'1200'},
 {h:'105',l:'95',v:null,q:'1200'},{h:'105',l:'95',v:'-1',q:'1200'},
 {h:'Infinity',l:'95',v:'12',q:'1200'}])tickerMetrics(s,item);
console.log(JSON.stringify({unchanged:before===JSON.stringify(s.metrics),metrics:s.metrics}));
"""
    )
    result = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {
        "unchanged": True,
        "metrics": {"high": 105, "low": 95, "volume": 12, "turnover": 1200},
    }


def test_new_catalog_asset_appears_after_the_first_four_cards(monkeypatch):
    from dataclasses import replace
    from btc_analyzer.assets import ASSETS, MARKETS

    fifth = replace(ASSETS["BTC"], code="ADA", name="에이다", card_id="cardano")
    monkeypatch.setitem(ASSETS, "ADA", fifth)
    monkeypatch.setitem(MARKETS, "ADA", fifth)
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    assert app.button(key="open_ADA").label == "에이다 차트 열기"
    assert sum(item.value.count('data-quote-symbol="ADAUSDT"') for item in app.markdown) == 1
    assert not app.get("plotly_chart")


def test_a_search_and_market_filter_keep_only_matching_rows():
    app = AppTest.from_file(ROOT / "web_app.py", default_timeout=30).run()
    app.text_input(key="board_search").set_value("msft").run()
    assert {button.key for button in app.button} == {"open_MSFT"}
    app.button(key="open_MSFT").click().run()
    assert not app.exception and app.query_params["market"] == "MSFT"
    assert len(app.get("plotly_chart")) == 1
