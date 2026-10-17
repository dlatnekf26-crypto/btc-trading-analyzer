"""Source-reported daily US spot ETF flows, in USD millions."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re

from btc_analyzer.data.market_context import _download

ETF_URLS = {
    "BTC": "https://farside.co.uk/bitcoin-etf-flow-all-data/",
    "ETH": "https://farside.co.uk/ethereum-etf-flow-all-data/",
    "SOL": "https://farside.co.uk/sol/",
}


@dataclass(frozen=True)
class ETFDay:
    at: date
    funds: tuple[tuple[str, float | None], ...]
    net: float | None


@dataclass(frozen=True)
class ETFFlows:
    asset: str
    days: tuple[ETFDay, ...]
    fetched_at: datetime

    @property
    def latest(self):
        return next((day for day in reversed(self.days) if day.net is not None), None)


class _Tables(HTMLParser):
    """Only table cell text, bounded by the HTTP body limit; never execute HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _amount(text):
    value = text.strip().replace(",", "").replace("−", "-")
    if value in ("", "-", "—", "–", "N/A"):
        return None  # Unpublished/ambiguous cells are never invented as zero.
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        raise ValueError("Invalid ETF flow cell")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid ETF flow") from exc
    if not number.is_finite() or abs(number) > 1_000_000:
        raise ValueError("ETF flow outside USD-million bounds")
    return float(number)


def parse_etf_flows(body: bytes, asset: str, now: datetime):
    if asset not in ETF_URLS or now.tzinfo is None or len(body) > 2_000_000:
        raise ValueError("Invalid ETF request")
    parser = _Tables()
    parser.feed(body.decode("utf-8"))
    for table in parser.tables:
        anchor = {"BTC": "IBIT", "ETH": "ETHA", "SOL": "BSOL"}[asset]
        original_header = next(
            (
                row
                for row in table
                if row
                and row[0].casefold() in ("date", "")
                and anchor in row
                and row[-1].casefold() in ("total", "")
            ),
            None,
        )
        if original_header is None or not 3 <= len(original_header) <= 40:
            continue
        header = [*original_header[:-1], "Total"]
        names = tuple(header[1:-1])
        if anchor not in names:
            continue  # A wrong/redirected asset table cannot become this flow.
        if len(set(names)) != len(names) or any(not re.fullmatch(r"[A-Z0-9-]{2,12}", n) for n in names):
            raise ValueError("Unexpected ETF fund columns")
        days = {}
        for row in table[table.index(original_header) + 1 :]:
            if not row:
                continue
            at = None
            for pattern in ("%d %b %Y", "%d %b %y", "%Y-%m-%d"):
                try:
                    at = datetime.strptime(row[0], pattern).date()
                    break
                except ValueError:
                    pass
            if at is None:
                continue  # Fee, seed, total and average rows are not trading days.
            if len(row) != len(header) or at > now.date() or at < date(2024, 1, 1):
                raise ValueError("Invalid ETF date or table shape")
            values = tuple(_amount(cell) for cell in row[1:])
            funds, net = tuple(zip(names, values[:-1])), values[-1]
            if net is not None and all(v is not None for v in values[:-1]):
                if abs(sum(values[:-1]) - net) > 0.11 * len(names):
                    raise ValueError("ETF total does not match reported funds")
            day = ETFDay(at, funds, net)
            if at in days and days[at] != day:
                raise ValueError("Conflicting ETF trading dates")
            days[at] = day
        if days:
            return ETFFlows(asset, tuple(days[key] for key in sorted(days)[-60:]), now)
    raise ValueError("ETF data table unavailable")


def fetch_etf(key, now):
    asset = key.removeprefix("etf_")
    return parse_etf_flows(_download(ETF_URLS[asset], max_bytes=2_000_000), asset, now)
