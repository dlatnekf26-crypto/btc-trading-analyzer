"""Asset selection isolates candles/news while reusing one analysis workflow."""

import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from btc_analyzer.assets import ASSETS, asset_news, price_text
from btc_analyzer.analysis.monthly_heatmap import monthly_heatmap
from btc_analyzer.ui.live_prices import live_prices_html


def test_asset_identity_news_routing_and_small_price_precision():
    assert len({a.symbol for a in ASSETS.values()}) == 4
    assert asset_news("Solana ETF inflows surge") == ("SOL",)
    assert asset_news("Ethereum ETF inflows create ripple effects") == ("ETH",)
    from btc_analyzer.data.market_context import crypto_relevance

    assert not crypto_relevance("Oil surge creates ripple effects across markets")
    assert price_text(0.000031) == "0.000031"
    assert asset_news("XRP and Ethereum markets rise") == ("ETH", "XRP")
    assert asset_news("Crypto markets react to Fed rate cut") == tuple(ASSETS)
    assert asset_news("Dogecoin ETF approved") == ()
    assert price_text(1.1532) == "1.1532" and price_text(100000) == "100,000.00"
    assert len({live_prices_html(code) for code in ASSETS}) == 1


def test_sol_listing_month_is_excluded_from_historical_average():
    frame = pd.DataFrame(
        dict(open=[100, 100], high=[200, 150], low=[100, 100], close=[200, 150]),
        index=pd.to_datetime(["2020-08-01", "2021-08-01"], utc=True),
    )
    result = monthly_heatmap(frame, pd.Timestamp("2026-10-01T00:00Z"), listed_month=(2020, 8))
    august = result.averages[7]
    assert august.samples == 1 and august.change == 0.5
    assert next(c for c in result.cells if c.year == 2020 and c.month == 8).status == "partial"


@pytest.mark.usefixtures("offline_dashboard")
def test_four_assets_switch_complete_dashboard_forecast_and_back_without_cross_asset_data():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=45).run()
    anchors = {}
    for code in ("BTC", "ETH", "SOL", "XRP", "BTC"):
        next(x for x in app.get("button_group") if x.label == "분석할 시장").set_value(code)
        app.session_state["dashboard_tab"] = "시장 개요"
        app.run()
        assert not app.exception and not app.error
        assert any(ASSETS[code].symbol in caption.value for caption in app.caption)
        widget = app.get("iframe")[0].proto.srcdoc
        assert widget == live_prices_html("BTC")
        assert any(
            f'id="btc-live-selection" data-symbol="{ASSETS[code].stream_symbol}"' in item.value
            for item in app.markdown
        )
        assert len(app.get("iframe")) == 1
        assert any(f'data-symbol="{ASSETS[code].stream_symbol}"' in item.value for item in app.markdown)
        assert any(f"{ASSETS[code].name} 월별 등락" in item.value for item in app.markdown)
        for tab in ("미래 예측",):
            app.session_state["dashboard_tab"] = tab
            app.run()
            assert not app.exception and not app.error
        chart = json.loads(app.get("plotly_chart")[0].proto.spec)
        anchor = chart["layout"]["meta"]["btcLive"]["anchor"]
        if code in anchors:
            assert anchor == anchors[code]
        anchors[code] = anchor
    assert anchors["BTC"] > anchors["ETH"] > anchors["SOL"] > anchors["XRP"]
