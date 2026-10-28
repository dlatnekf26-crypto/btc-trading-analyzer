"""Common Korean queries reach real catalog entries without extra requests."""

import pytest
from btc_analyzer.assets import MARKETS
from btc_analyzer.ui.market_board import matching_markets


@pytest.mark.parametrize(
    "query,code",
    [
        ("삼전", "SAMSUNG"),
        ("ㅅㅅㅈㅈ", "SAMSUNG"),
        ("삼성 전자", "SAMSUNG"),
        ("마소", "MSFT"),
        ("NVIDIA", "NVDA"),
        ("005930", "SAMSUNG"),
        ("sk hynix", "SKHYNIX"),
        ("구글", "GOOGL"),
    ],
)
def test_search_aliases_initials_and_spacing(query, code):
    assert code in matching_markets(MARKETS, query)


def test_empty_unknown_and_markup_queries_are_safe():
    assert matching_markets(MARKETS, "  ") == tuple(MARKETS)
    assert not matching_markets(MARKETS, "<script>")
    assert not matching_markets(MARKETS, "OAI")
