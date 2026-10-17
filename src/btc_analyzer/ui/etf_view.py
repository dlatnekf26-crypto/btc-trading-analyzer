"""Light native ETF cards; separate daily publication from live crypto quotes."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st
from btc_analyzer import __checkout_signature__
from btc_analyzer.data.etf_flows import ETF_URLS, ETFFlows, fetch_etf
from btc_analyzer.data.market_context import MarketContextService, UTC


@st.cache_resource(max_entries=1, show_spinner=False, on_release=lambda service: service.close())
def etf_service(source_version):
    return MarketContextService(
        fetcher=fetch_etf,
        keys=tuple("etf_" + code for code in ETF_URLS),
        refresh_intervals={"etf_" + code: 600 for code in ETF_URLS},
        workers=2,
    )


def etf_card(code, feed, now):
    value = feed.value
    latest = value.latest if isinstance(value, ETFFlows) and value.asset == code else None
    title = f"{code} · 미국 현물 ETF"
    info, total, graph = "발표 자료를 불러오는 중…" if feed.loading else "자료원 연결 대기", "—", ""
    if latest:
        total = f"{latest.net:+,.1f}"
        info = f"{latest.at:%Y.%m.%d} 거래일 · " + (
            "순유입" if latest.net > 0 else "순유출" if latest.net < 0 else "순유입 0"
        )
        recent = value.days[-10:]
        scale = max((abs(day.net) for day in recent if day.net is not None), default=1) or 1
        bars = []
        for i, day in enumerate(recent):
            if day.net is None:
                bars.append(
                    f'<circle cx="{i * 24 + 12}" cy="32" r="2" fill="#aab4c2"><title>{day.at} · 미완결</title></circle>'
                )
            else:
                height = max(1, abs(day.net) / scale * 26)
                y = 32 - height if day.net >= 0 else 32
                color = "#09845c" if day.net >= 0 else "#d63851"
                bars.append(
                    f'<rect x="{i * 24 + 4}" y="{y:.1f}" width="16" height="{height:.1f}" rx="3" fill="{color}"><title>{day.at} · {day.net:+.1f} 백만 USD</title></rect>'
                )
        graph = (
            '<svg viewBox="0 0 240 64" role="img" aria-label="최근 ETF 일별 순유입"><path d="M0 32H240" stroke="#e7ecf3"/>'
            + "".join(bars)
            + "</svg>"
        )
        window = value.days[-5:]
        if len(window) == 5 and all(day.net is not None for day in window):
            info += f" · 최근 5거래일 {sum(day.net for day in window):+,.1f}M"
        if value.days[-1].net is None:
            info += f" · {value.days[-1].at:%m.%d} 집계 중"
        if (
            now.date() - latest.at > timedelta(days=4)
            or feed.error
            or (feed.updated_at and now - feed.updated_at > timedelta(minutes=20))
        ):
            info += " · 마지막 발표 / 갱신 지연"
    elif feed.error:
        info = "조회 지연 · 수급 자료가 도착하면 표시합니다"
    checked = (
        f"확인 {feed.updated_at.astimezone(ZoneInfo('Asia/Seoul')):%m.%d %H:%M} KST"
        if feed.updated_at
        else ""
    )
    return (
        f'<article class="btc-etf-card" data-asset="{code}"><span>{title}</span>'
        f"<strong>{total}<small> 백만 USD</small></strong><p>{escape(info)}</p>{graph}<p>{checked}</p>"
        f'<a href="{ETF_URLS[code]}" target="_blank" rel="noopener noreferrer">Farside Investors · 출처 ↗</a></article>'
    )


@st.fragment(run_every=15)
def render_etf_flows():
    now = datetime.now(UTC)
    context = etf_service(__checkout_signature__).snapshot()
    st.markdown(
        "<style>.btc-etf-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.btc-etf-card{background:#fff;border:1px solid #e7ecf3;border-radius:18px;padding:16px;min-width:0}.btc-etf-card>span{font-weight:650;font-size:13px}.btc-etf-card strong{display:block;font-size:26px;margin:8px 0;font-variant-numeric:tabular-nums}.btc-etf-card small{font-size:11px;font-weight:400}.btc-etf-card p,.btc-etf-card a{font-size:11px;color:#66758b;line-height:1.55;overflow-wrap:anywhere}.btc-etf-card svg{display:block;width:100%;height:64px}@media(max-width:600px){.btc-etf-card{padding:12px}.btc-etf-card strong{font-size:22px}}</style><strong>ETF 자금 흐름</strong>",
        unsafe_allow_html=True,
    )
    st.caption("미국 BTC·ETH·SOL 현물 ETF · 일별 발표 · 10분마다 확인 · XRP는 확인 가능한 자료원 연결 대기")
    st.markdown(
        '<div class="btc-etf-grid">'
        + "".join(etf_card(code, context.feed("etf_" + code), now) for code in ETF_URLS)
        + '<article class="btc-etf-card" data-asset="XRP"><span>XRP · 미국 현물 ETF</span><strong>—</strong><p>집계 자료 미연결 · 확인된 유입·유출 자료 없음</p><p>검증된 일별 집계 자료가 아직 연결되지 않았습니다.</p></article>'
        + "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("펀드별 수급 · 최신 발표"):
        for code in ETF_URLS:
            feed = context.feed("etf_" + code)
            latest = feed.value.latest if isinstance(feed.value, ETFFlows) else None
            if latest:
                st.caption(f"{code} · {latest.at:%Y.%m.%d} · 백만 USD · —는 미제공, 0은 원자료의 0")
                rows = "".join(
                    f"<tr><td>{escape(name)}</td><td>{'—' if value is None else f'{value:+,.1f}'}</td></tr>"
                    for name, value in latest.funds
                )
                st.markdown(
                    '<table style="width:100%;font-size:13px"><thead><tr><th>펀드</th><th>순유입 · 백만 USD</th></tr></thead><tbody>'
                    + rows
                    + "</tbody></table>",
                    unsafe_allow_html=True,
                )
