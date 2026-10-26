"""Optional, read-only KIS NXT intraday quotes; never submits trading orders."""

from datetime import datetime, timedelta, timezone
import math
from threading import Lock
from zoneinfo import ZoneInfo

import requests

from btc_analyzer.assets import STOCK_MARKETS, EXCHANGE_HISTORY
from btc_analyzer.data.extended_quotes import ExtendedQuote

SEOUL = ZoneInfo("Asia/Seoul")
BASE = "https://openapi.koreainvestment.com:9443"
CODES = {
    "nxt_" + a.card_id.removeprefix("macro-"): a.symbol[:6]
    for c, a in STOCK_MARKETS.items()
    if EXCHANGE_HISTORY[c].calendar == "KRX"
}


def nxt_session(now):
    local = now.astimezone(SEOUL)
    minute = local.hour * 60 + local.minute
    if local.weekday() < 5:
        if 480 <= minute < 530:
            return "pre"
        if 940 <= minute < 1200:
            return "post"
    return None


def parse_nxt(payload, now):
    if payload.get("rt_cd") != "0" or not isinstance(payload.get("output2"), list):
        raise ValueError("NXT quote unavailable")
    found = []
    for row in payload["output2"][:30]:
        try:
            at = datetime.strptime(row["stck_bsop_date"] + row["stck_cntg_hour"], "%Y%m%d%H%M%S").replace(
                tzinfo=SEOUL
            )
            if isinstance(row["stck_prpr"], bool):
                continue
            price = float(row["stck_prpr"])
            session = nxt_session(at)
            if (
                session
                and math.isfinite(price)
                and price > 0
                and at.date() == now.astimezone(SEOUL).date()
                and timedelta(0) <= now - at <= timedelta(minutes=3)
            ):
                found.append(ExtendedQuote(price, at.astimezone(timezone.utc), session, "KIS NXT"))
        except (KeyError, TypeError, ValueError):
            continue
    if not found:
        raise ValueError("No recent NXT extended-session trade")
    return max(found, key=lambda quote: quote.as_of)


class NXTClient:
    def __init__(self, key, secret):
        self.key, self.secret = key, secret
        self._token, self._expires, self._retry = (
            "",
            datetime.min.replace(tzinfo=timezone.utc),
            datetime.min.replace(tzinfo=timezone.utc),
        )
        self._lock = Lock()
        self._last = {}

    def _json(self, method, path, **kwargs):
        response = requests.request(method, BASE + path, timeout=(2, 3), **kwargs)
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ValueError("NXT response too large")
        return response.json()

    def token(self, now):
        with self._lock:
            if self._token and now < self._expires:
                return self._token
            if now < self._retry:
                raise ValueError("NXT authentication retry pending")
            self._retry = now + timedelta(minutes=2)
            result = self._json(
                "POST",
                "/oauth2/tokenP",
                json={"grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret},
            )
            token = result.get("access_token")
            seconds = result.get("expires_in")
            if (
                not isinstance(token, str)
                or not token
                or any(c in token for c in "\r\n")
                or not isinstance(seconds, (int, float))
                or not 60 < seconds <= 86400
            ):
                raise ValueError("NXT authentication unavailable")
            self._token, self._expires = token, now + timedelta(seconds=seconds - 60)
            return token

    def fetch(self, key, now):
        if not nxt_session(now):
            return self._last.get(key)
        payload = self._json(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            headers={
                "authorization": "Bearer " + self.token(now),
                "appkey": self.key,
                "appsecret": self.secret,
                "tr_id": "FHKST03010200",
                "custtype": "P",
                "content-type": "application/json; charset=utf-8",
            },
            params={
                "FID_COND_MRKT_DIV_CODE": "NX",
                "FID_INPUT_ISCD": CODES[key],
                "FID_INPUT_HOUR_1": now.astimezone(SEOUL).strftime("%H%M%S"),
                "FID_PW_DATA_INCU_YN": "Y",
                "FID_ETC_CLS_CODE": "",
            },
        )
        result = parse_nxt(payload, now)
        self._last[key] = result
        return result
