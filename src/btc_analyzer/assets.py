"""Shared market identities; adding an asset does not copy the dashboard."""

from dataclasses import dataclass
from datetime import date
import re


@dataclass(frozen=True)
class Asset:
    code: str
    name: str
    card_id: str
    decimals: int
    listed: date
    news_pattern: str
    pair: str | None = None

    @property
    def symbol(self):
        return self.pair or f"{self.code}/USDT"

    @property
    def stream_symbol(self):
        return self.pair or f"{self.code}USDT"


ASSETS = {
    asset.code: asset
    for asset in (
        Asset(
            "BTC", "비트코인", "binance", 2, date(2017, 8, 17), r"\bBTC\b|bitcoin(?!\s+cash)|비트코인(?!캐시)"
        ),
        Asset("ETH", "이더리움", "ethereum", 2, date(2017, 8, 17), r"\bETH\b|ethereum|이더리움"),
        Asset("SOL", "솔라나", "solana", 2, date(2020, 8, 11), r"\bSOL\b|solana|솔라나"),
        Asset("XRP", "리플", "ripple", 4, date(2018, 5, 4), r"\bXRP\b|ripple(?!\s+effects?\b)|리플"),
        Asset("BNB", "비앤비", "coin-bnb", 4, date(2017, 11, 6), r"\bBNB\b|binancecoin|비앤비"),
        Asset("DOGE", "도지코인", "coin-doge", 5, date(2019, 7, 5), r"\bDOGE\b|dogecoin|도지코인"),
        Asset("ADA", "에이다", "coin-ada", 4, date(2018, 4, 17), r"\bADA\b|cardano|에이다"),
        Asset("AVAX", "아발란체", "coin-avax", 3, date(2020, 9, 22), r"\bAVAX\b|avalanche|아발란체"),
        Asset("LINK", "체인링크", "coin-link", 3, date(2019, 1, 16), r"\bLINK\b|chainlink|체인링크"),
        Asset("DOT", "폴카닷", "coin-dot", 4, date(2020, 8, 18), r"\bDOT\b|polkadot|폴카닷"),
        Asset("LTC", "라이트코인", "coin-ltc", 2, date(2017, 12, 13), r"\bLTC\b|litecoin|라이트코인"),
        Asset("BCH", "비트코인캐시", "coin-bch", 2, date(2019, 11, 28), r"\bBCH\b|bitcoin cash|비트코인캐시"),
        Asset("TRX", "트론", "coin-trx", 5, date(2018, 6, 11), r"\bTRX\b|tron|트론"),
        Asset("SUI", "수이", "coin-sui", 4, date(2023, 5, 3), r"\bSUI\b|sui|수이"),
        Asset(
            "NEAR", "니어프로토콜", "coin-near", 4, date(2020, 10, 14), r"\bNEAR\b|near protocol|니어프로토콜"
        ),
        Asset("UNI", "유니스왑", "coin-uni", 4, date(2020, 9, 17), r"\bUNI\b|uniswap|유니스왑"),
    )
}


COIN_IDS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "binancecoin": "BNB",
    "dogecoin": "DOGE",
    "cardano": "ADA",
    "avalanche-2": "AVAX",
    "chainlink": "LINK",
    "polkadot": "DOT",
    "litecoin": "LTC",
    "bitcoin-cash": "BCH",
    "tron": "TRX",
    "sui": "SUI",
    "near": "NEAR",
    "uniswap": "UNI",
}

STOCK_MARKETS = {
    asset.code: asset
    for asset in (
        Asset("SAMSUNG", "삼성전자", "macro-samsung", 0, date(1975, 6, 11), "", "005930.KS"),
        Asset("SKHYNIX", "SK하이닉스", "macro-skhynix", 0, date(1996, 12, 26), "", "000660.KS"),
        Asset("SAMSUNG_EM", "삼성전기", "macro-samsungem", 0, date(1979, 2, 27), "", "009150.KS"),
        Asset("LS_ELECTRIC", "LS일렉트릭", "macro-lselectric", 0, date(1994, 7, 11), "", "010120.KS"),
        Asset("HYUNDAI", "현대차", "macro-hyundai", 0, date(1974, 6, 28), "", "005380.KS"),
        Asset("LGES", "LG에너지솔루션", "macro-lges", 0, date(2022, 1, 27), "", "373220.KS"),
        Asset("NAVER", "네이버", "macro-naver", 0, date(2002, 10, 29), "", "035420.KS"),
        Asset("KAKAO", "카카오", "macro-kakao", 0, date(1999, 11, 11), "", "035720.KS"),
        Asset("KIA", "기아", "macro-kia", 0, date(1973, 7, 21), "", "000270.KS"),
        Asset("SAMSUNG_BIO", "삼성바이오로직스", "macro-samsungbio", 0, date(2016, 11, 10), "", "207940.KS"),
        Asset("CELLTRION", "셀트리온", "macro-celltrion", 0, date(2005, 7, 19), "", "068270.KS"),
        Asset("KB", "KB금융", "macro-kb", 0, date(2008, 10, 10), "", "105560.KS"),
        Asset("SHINHAN", "신한지주", "macro-shinhan", 0, date(2001, 9, 10), "", "055550.KS"),
        Asset("HANWHA_AERO", "한화에어로스페이스", "macro-hanwhaaero", 0, date(1987, 5, 27), "", "012450.KS"),
        Asset("HD_HYUNDAI", "HD현대중공업", "macro-hdhyundai", 0, date(2021, 9, 17), "", "329180.KS"),
        Asset("HYUNDAI_MOBIS", "현대모비스", "macro-hyundaimobis", 0, date(1989, 9, 5), "", "012330.KS"),
        Asset("POSCO", "POSCO홀딩스", "macro-posco", 0, date(1988, 6, 10), "", "005490.KS"),
        Asset("SAMSUNG_SDI", "삼성SDI", "macro-samsungsdi", 0, date(1979, 2, 27), "", "006400.KS"),
        Asset("LG_CHEM", "LG화학", "macro-lgchem", 0, date(2001, 4, 25), "", "051910.KS"),
        Asset("SAMSUNG_LIFE", "삼성생명", "macro-samsunglife", 0, date(2010, 5, 12), "", "032830.KS"),
        Asset("MSTR", "스트래티지", "macro-mstr", 2, date(1998, 6, 11), "", "MSTR"),
        Asset("GOOGL", "알파벳", "macro-googl", 2, date(2004, 8, 19), "", "GOOGL"),
        Asset("TSLA", "테슬라", "macro-tsla", 2, date(2010, 6, 29), "", "TSLA"),
        Asset("META", "메타", "macro-meta", 2, date(2012, 5, 18), "", "META"),
        Asset("MSFT", "마이크로소프트", "macro-msft", 2, date(1986, 3, 13), "", "MSFT"),
        Asset("AAPL", "애플", "macro-aapl", 2, date(1980, 12, 12), "", "AAPL"),
        Asset("NVDA", "엔비디아", "macro-nvda", 2, date(1999, 1, 22), "", "NVDA"),
        Asset("MU", "마이크론", "macro-mu", 2, date(1984, 6, 1), "", "MU"),
        Asset("SNDK", "샌디스크", "macro-sndk", 2, date(2025, 2, 13), "", "SNDK"),
        Asset("AMZN", "아마존", "macro-amzn", 2, date(1997, 5, 15), "", "AMZN"),
        Asset("AVGO", "브로드컴", "macro-avgo", 2, date(2009, 8, 6), "", "AVGO"),
        Asset("AMD", "AMD", "macro-amd", 2, date(1972, 9, 27), "", "AMD"),
        Asset("PLTR", "팔란티어", "macro-pltr", 2, date(2020, 9, 30), "", "PLTR"),
        Asset("NFLX", "넷플릭스", "macro-nflx", 2, date(2002, 5, 23), "", "NFLX"),
        Asset("INTC", "인텔", "macro-intc", 2, date(1971, 10, 13), "", "INTC"),
        Asset("QCOM", "퀄컴", "macro-qcom", 2, date(1991, 12, 13), "", "QCOM"),
        Asset("ARM", "암", "macro-arm", 2, date(2023, 9, 14), "", "ARM"),
        Asset("COIN", "코인베이스", "macro-coin", 2, date(2021, 4, 14), "", "COIN"),
        Asset("COST", "코스트코", "macro-cost", 2, date(1985, 12, 5), "", "COST"),
        Asset("ADBE", "어도비", "macro-adbe", 2, date(1986, 8, 13), "", "ADBE"),
        Asset("LG_ELECTRONICS", "LG전자", "macro-lgelectronics", 0, date(2002, 4, 22), "", "066570.KS"),
        Asset("SAMSUNG_CT", "삼성물산", "macro-samsungct", 0, date(2014, 12, 18), "", "028260.KS"),
        Asset("SAMSUNG_FIRE", "삼성화재", "macro-samsungfire", 0, date(1975, 6, 30), "", "000810.KS"),
        Asset("HANA", "하나금융지주", "macro-hana", 0, date(2005, 12, 12), "", "086790.KS"),
        Asset("WOORI", "우리금융지주", "macro-woori", 0, date(2019, 2, 13), "", "316140.KS"),
        Asset("KT", "KT", "macro-kt", 0, date(1998, 12, 23), "", "030200.KS"),
        Asset("SK_TELECOM", "SK텔레콤", "macro-sktelecom", 0, date(1989, 11, 7), "", "017670.KS"),
        Asset("KEPCO", "한국전력", "macro-kepco", 0, date(1989, 8, 10), "", "015760.KS"),
        Asset(
            "DOOSAN_ENERGY", "두산에너빌리티", "macro-doosanenergy", 0, date(2000, 10, 25), "", "034020.KS"
        ),
        Asset("HANWHA_OCEAN", "한화오션", "macro-hanwhaocean", 0, date(2001, 2, 2), "", "042660.KS"),
        Asset("HD_KSOE", "HD한국조선해양", "macro-hdksoe", 0, date(1999, 8, 24), "", "009540.KS"),
        Asset("HYUNDAI_ROTEM", "현대로템", "macro-hyundairotem", 0, date(2013, 10, 30), "", "064350.KS"),
        Asset("KOREA_AERO", "한국항공우주", "macro-koreaaero", 0, date(2011, 6, 30), "", "047810.KS"),
        Asset("LIG_NEX1", "LIG넥스원", "macro-lignex1", 0, date(2015, 10, 2), "", "079550.KS"),
        Asset("HANMI_SEMI", "한미반도체", "macro-hanmisemi", 0, date(2005, 7, 22), "", "042700.KS"),
        Asset(
            "HYUNDAI_ELECTRIC",
            "HD현대일렉트릭",
            "macro-hyundaielectric",
            0,
            date(2017, 5, 10),
            "",
            "267260.KS",
        ),
        Asset("HMM", "HMM", "macro-hmm", 0, date(1995, 10, 5), "", "011200.KS"),
        Asset("KOREAN_AIR", "대한항공", "macro-koreanair", 0, date(1966, 3, 18), "", "003490.KS"),
        Asset("AMORE", "아모레퍼시픽", "macro-amore", 0, date(2006, 6, 29), "", "090430.KS"),
        Asset("KTG", "KT&G", "macro-ktg", 0, date(1999, 10, 8), "", "033780.KS"),
        Asset("TSM", "TSMC", "macro-tsm", 2, date(1997, 10, 8), "", "TSM"),
        Asset("ORCL", "오라클", "macro-orcl", 2, date(1986, 3, 12), "", "ORCL"),
        Asset("CRM", "세일즈포스", "macro-crm", 2, date(2004, 6, 23), "", "CRM"),
        Asset("JPM", "JP모건 체이스", "macro-jpm", 2, date(1980, 3, 17), "", "JPM"),
        Asset("BAC", "뱅크오브아메리카", "macro-bac", 2, date(1980, 3, 17), "", "BAC"),
        Asset("V", "비자", "macro-v", 2, date(2008, 3, 19), "", "V"),
        Asset("MA", "마스터카드", "macro-ma", 2, date(2006, 5, 25), "", "MA"),
        Asset("WMT", "월마트", "macro-wmt", 2, date(1972, 8, 25), "", "WMT"),
        Asset("LLY", "일라이 릴리", "macro-lly", 2, date(1972, 6, 1), "", "LLY"),
        Asset("UNH", "유나이티드헬스", "macro-unh", 2, date(1984, 10, 17), "", "UNH"),
        Asset("JNJ", "존슨앤드존슨", "macro-jnj", 2, date(1962, 1, 2), "", "JNJ"),
        Asset("XOM", "엑슨모빌", "macro-xom", 2, date(1962, 1, 2), "", "XOM"),
        Asset("CVX", "셰브론", "macro-cvx", 2, date(1962, 1, 2), "", "CVX"),
        Asset("KO", "코카콜라", "macro-ko", 2, date(1962, 1, 2), "", "KO"),
        Asset("PEP", "펩시코", "macro-pep", 2, date(1972, 6, 1), "", "PEP"),
        Asset("DIS", "월트디즈니", "macro-dis", 2, date(1962, 1, 2), "", "DIS"),
        Asset("UBER", "우버", "macro-uber", 2, date(2019, 5, 10), "", "UBER"),
        Asset("SHOP", "쇼피파이", "macro-shop", 2, date(2015, 5, 21), "", "SHOP"),
        Asset("HOOD", "로빈후드", "macro-hood", 2, date(2021, 7, 29), "", "HOOD"),
        Asset("SOFI", "소파이", "macro-sofi", 2, date(2021, 6, 1), "", "SOFI"),
    )
}
INDEX_MARKETS = {
    "KOSDAQ": Asset("KOSDAQ", "코스닥", "macro-kosdaq", 2, date(2000, 1, 1), "", "^KQ11"),
    "NASDAQ": Asset("NASDAQ", "나스닥 종합", "macro-nasdaq", 2, date(2000, 1, 1), "", "^IXIC"),
    "RUSSELL": Asset("RUSSELL", "러셀2000", "macro-russell", 2, date(2000, 1, 1), "", "^RUT"),
    "DOW": Asset("DOW", "다우존스", "macro-dow", 2, date(2000, 1, 1), "", "^DJI"),
    "NIKKEI": Asset("NIKKEI", "니케이225", "macro-nikkei", 2, date(1984, 1, 4), "", "^N225"),
    "NQ": Asset("NQ", "나스닥100 선물", "macro-nq", 2, date(1999, 6, 21), "", "NQ=F"),
    "KOSPI": Asset("KOSPI", "코스피", "macro-kospi", 2, date(1999, 1, 1), "", "^KS11"),
    "SP500": Asset("SP500", "S&P 500", "macro-sp500", 2, date(1957, 3, 4), "", "^GSPC"),
}
MACRO_MARKETS = {
    "NATGAS": Asset("NATGAS", "천연가스 선물", "macro-natgas", 3, date(2000, 8, 30), "", "NG=F"),
    "COPPER": Asset("COPPER", "구리 선물", "macro-copper", 3, date(2000, 8, 30), "", "HG=F"),
    "SILVER": Asset("SILVER", "은 선물", "macro-silver", 3, date(2000, 8, 30), "", "SI=F"),
    "GOLD": Asset("GOLD", "금 선물", "macro-gold", 2, date(2000, 8, 30), "", "GC=F"),
    "OIL": Asset("OIL", "WTI 원유 선물", "macro-oil", 2, date(2000, 8, 23), "", "CL=F"),
    "TNX": Asset("TNX", "미국채 10년 금리", "macro-tnx", 3, date(1962, 1, 2), "", "^TNX"),
    "TYX": Asset("TYX", "미국채 30년 금리", "macro-tyx", 3, date(1977, 2, 15), "", "^TYX"),
}
SESSION_MARKETS = {**INDEX_MARKETS, **STOCK_MARKETS, **MACRO_MARKETS}
MARKETS = {**ASSETS, **SESSION_MARKETS}


@dataclass(frozen=True)
class ExchangeHistory:
    currency: str
    timezone: str
    exchange: str
    source: str
    calendar: str = "CME_Equity"
    kind: str = "FUTURE"
    unit: str = "pt"


EXCHANGE_HISTORY = {
    "DOW": ExchangeHistory("USD", "America/New_York", "US", "다우존스 현물지수", "NYSE", "INDEX"),
    "RUSSELL": ExchangeHistory("USD", "America/New_York", "US", "러셀2000 현물지수", "NYSE", "INDEX"),
    "NASDAQ": ExchangeHistory("USD", "America/New_York", "US", "나스닥 종합 현물지수", "NYSE", "INDEX"),
    "KOSDAQ": ExchangeHistory("KRW", "Asia/Seoul", "KRX", "코스닥 현물지수", "KRX", "INDEX"),
    "SILVER": ExchangeHistory(
        "USD",
        "America/New_York",
        "COMEX",
        "은 연속 선물",
        "CMEGlobex_EnergyAndMetals",
        "FUTURE",
        "USD/트로이온스",
    ),
    "COPPER": ExchangeHistory(
        "USD",
        "America/New_York",
        "COMEX",
        "구리 연속 선물",
        "CMEGlobex_EnergyAndMetals",
        "FUTURE",
        "USD/파운드",
    ),
    "NATGAS": ExchangeHistory(
        "USD",
        "America/New_York",
        "NYMEX",
        "천연가스 연속 선물",
        "CMEGlobex_EnergyAndMetals",
        "FUTURE",
        "USD/MMBtu",
    ),
    "NIKKEI": ExchangeHistory("JPY", "Asia/Tokyo", "JPX", "니케이225 현물지수", "JPX", "INDEX"),
    "GOLD": ExchangeHistory(
        "USD",
        "America/New_York",
        "COMEX",
        "금 연속 선물",
        "CMEGlobex_EnergyAndMetals",
        "FUTURE",
        "USD/트로이온스",
    ),
    "OIL": ExchangeHistory(
        "USD", "America/New_York", "NYMEX", "WTI 연속 선물", "CMEGlobex_EnergyAndMetals", "FUTURE", "USD/배럴"
    ),
    "TNX": ExchangeHistory(
        "USD", "America/Chicago", "CBOE", "미국채 10년 금리 지수", "US_YIELD", "INDEX", "%"
    ),
    "TYX": ExchangeHistory(
        "USD", "America/Chicago", "CBOE", "미국채 30년 금리 지수", "US_YIELD", "INDEX", "%"
    ),
    "NQ": ExchangeHistory("USD", "America/New_York", "CME", "CME NQ 연속 선물"),
    "KOSPI": ExchangeHistory("KRW", "Asia/Seoul", "KRX", "KRX 코스피 종합지수", "KRX", "INDEX"),
    "SP500": ExchangeHistory("USD", "America/New_York", "S&P", "S&P 500 현물지수", "NYSE", "INDEX"),
    **{
        code: ExchangeHistory("KRW", "Asia/Seoul", "KRX", "KRX 보통주", "KRX", "EQUITY", "KRW")
        for code, asset in STOCK_MARKETS.items()
        if asset.symbol.endswith(".KS")
    },
    **{
        code: ExchangeHistory(
            "USD",
            "America/New_York",
            "미국 거래소",
            "미국 주식 · 분봉 장전/장후 포함",
            "NYSE",
            "EQUITY",
            "USD",
        )
        for code, asset in STOCK_MARKETS.items()
        if not asset.symbol.endswith(".KS")
    },
}


def market_label(code):
    venue = EXCHANGE_HISTORY.get(code)
    return MARKETS[code].name if code == "SP500" or venue and venue.calendar == "KRX" else code


def asset_news(title):
    """An explicit coin headline belongs only to that coin; generic crypto to all."""
    matches = tuple(code for code, asset in ASSETS.items() if re.search(asset.news_pattern, title, re.I))
    if matches:
        return matches
    if re.search(r"dogecoin|\bdoge\b|도지|cardano|\bADA\b|카르다노", title, re.I):
        return ()
    return tuple(ASSETS)


def price_text(value, signed=False):
    """Keep small asset levels readable without rounding to whole dollars."""
    places = 6 if 0 < abs(value) < 0.01 else 4 if abs(value) < 10 else 2
    return format(value, f"{'+' if signed else ''},.{places}f")
