"""Chart average conventions shared by observed and conditional future paths."""

from btc_analyzer.assets import EXCHANGE_HISTORY

OVERSEAS_AVERAGES = ("ema_20", "ema_50", "ema_200")
DOMESTIC_AVERAGES = ("sma_20", "sma_60", "sma_120")
AVERAGE_COLORS = dict(zip(OVERSEAS_AVERAGES + DOMESTIC_AVERAGES, ("#dd9b24", "#3182f6", "#8c65da") * 2))


def market_averages(market):
    venue = EXCHANGE_HISTORY.get(market)
    return DOMESTIC_AVERAGES if venue and venue.calendar == "KRX" else OVERSEAS_AVERAGES
