"""Streamlit BTC research dashboard. V1 has no live-order code or credentials."""
# ruff: noqa: E402 -- checkout preparation must precede project imports.

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import sys

# Use this checkout even when a long-running host has imported an older release.
# Ordinary reruns preserve module identities and the optimized market caches.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path[:] = [str(PROJECT_ROOT), *[path for path in sys.path if path != str(PROJECT_ROOT)]]
from checkout_bootstrap import ensure_checkout

SOURCE_VERSION = globals().get("CHECKOUT_SOURCE_VERSION") or ensure_checkout(PROJECT_ROOT)

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from btc_analyzer.config import (
    AppConfig,
    IndicatorConfig,
    StrategyConfig,
    RiskConfig,
    TIMEFRAMES,
    MTF_MAP,
    COMPOSITE_TIMEFRAMES,
)
from btc_analyzer.candles import candle_boundary, candle_close
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.data.base_provider import DataError
from btc_analyzer.data.binance_provider import BinanceProvider
from btc_analyzer.ui.analysis_cache import feature_frame, research_analysis, combined_analysis
from btc_analyzer.risk.position_sizing import position_size
from btc_analyzer.paper.paper_trading import PaperTrader
from btc_analyzer.storage.database import Database, dumps
from btc_analyzer.strategy.composite import FRAME_LABELS, FRAME_WEIGHTS
from btc_analyzer.ui.charts import price_chart, indicator_chart, equity_chart, monte_chart
from btc_analyzer.ui.web_runtime import ResearchBusy, ResearchGate, runtime_paths
from btc_analyzer.ui.presentation import (
    BRAND,
    CSS,
    korean,
    market_hero,
    composite_cards,
    decision_panel,
    ichimoku_cards,
    LABELS,
)

load_dotenv(override=False)
logging.basicConfig(level=os.getenv("BTC_LOG_LEVEL", "INFO"))
st.set_page_config(page_title="BTC Signal Lab · Binance 시장 분석", page_icon="₿", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(BRAND, unsafe_allow_html=True)
app_environment = dict(os.environ)
if globals().get("PUBLIC_DEPLOYMENT"):
    app_environment["BTC_APP_MODE"] = "public"
    app_environment.setdefault("BTC_DEFAULT_EXCHANGE", "Binance")
    app_environment.setdefault("BTC_DEFAULT_SOURCE", "live")
try:
    runtime = runtime_paths(st.session_state, app_environment)
except OSError:
    st.error("저장 공간을 준비할 수 없습니다. 서버의 저장 공간과 쓰기 권한을 확인하세요.")
    st.stop()
PUBLIC = runtime.public
DB_PATH = runtime.database


@st.cache_resource
def research_gate() -> ResearchGate:
    return ResearchGate()


def request_market_refresh() -> None:
    st.session_state["market_refresh_sequence"] = st.session_state.get("market_refresh_sequence", 0) + 1


def open_history_comparison() -> None:
    st.session_state["dashboard_tab"] = "과거 유사성"
    st.session_state["similarity_timeframe"] = st.session_state.get("price_chart_timeframe", "1d")


with st.sidebar:
    st.subheader("시장 설정")
    source = st.selectbox(
        "데이터 모드",
        ["Demo · 합성 데이터", "Live · 공개 거래소 데이터"],
        index=int(app_environment.get("BTC_DEFAULT_SOURCE", "demo").lower() == "live"),
    )
    demo = source.startswith("Demo")
    exchange = st.selectbox(
        "거래소", ["Binance", "Upbit"], index=int(app_environment.get("BTC_DEFAULT_EXCHANGE") == "Upbit")
    )
    symbol = st.text_input(
        "거래 페어", "BTC/USDT" if exchange == "Binance" else "KRW-BTC", key=f"symbol_{exchange}"
    )
    quote_currency = symbol.split("/")[-1] if exchange == "Binance" else symbol.split("-")[0]
    st.caption(f"{exchange} 현물 · {quote_currency} 원본 가격 기준")
    timeframe = st.selectbox(
        "연구 시간대",
        [tf for tf in TIMEFRAMES if tf not in ("1w", "1M")],
        index=4,
        format_func=lambda tf: {"5m": "5분", "15m": "15분", **FRAME_LABELS}.get(tf, tf),
    )
    st.caption(
        "종합 판단은 수주~수개월 관점이에요. 일봉·주봉·월봉 85%, 단기 봉 15%를 반영해요. 이 선택은 별도의 연구·모의거래 기준입니다."
    )
    display_timezone = st.selectbox("표시 시간대", ["Asia/Seoul", "UTC", "America/New_York"])
    today = datetime.now(timezone.utc).date()
    date_range = st.date_input("분석 기간 · 실시간", (today - timedelta(days=30), today))
    bars = st.slider("Demo 평가 봉 수", 400, 1200 if PUBLIC else 2400, 800, 100, disabled=not demo)
    st.button("데이터 새로고침", on_click=request_market_refresh)
    auto_refresh = st.checkbox("Live 자동 업데이트 · 60초", value=False, disabled=demo)
    st.subheader("모의계좌 / 비용")
    capital = st.number_input(
        f"모의 자본 · {quote_currency}",
        min_value=100.0,
        value=10_000.0 if exchange == "Binance" else 10_000_000.0,
        step=100.0,
        key=f"capital_{exchange}_{quote_currency}",
    )
    risk_pct = st.number_input("거래당 계좌 위험 %", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
    fee_pct = st.number_input("수수료 %", min_value=0.0, max_value=5.0, value=0.1, step=0.01)
    slip_pct = st.number_input(
        "슬리피지 %",
        min_value=0.0,
        max_value=5.0,
        value=0.05,
        step=0.01,
        help="예상 가격보다 불리하게 체결되는 차이를 비용에 반영해요.",
    )
    st.caption("레버리지 1x · 통화는 선택 시장의 호가 통화")
    with st.expander("차트 · 지표 설정"):
        rsi_period = st.number_input("RSI period", 2, 50, 14)
        atr_period = st.number_input("ATR period", 2, 50, 14)
        bb_length = st.number_input("BB length", 5, 100, 20)
        bb_std = st.number_input("BB std", 1.0, 4.0, 2.0, step=0.1)
        fast_ema = st.selectbox("Fast trend EMA", [18, 20, 22], index=1)
        macd_fast = st.number_input("MACD fast", 2, 30, 12)
        macd_slow = st.number_input("MACD slow", 10, 100, 26)
        macd_signal = st.number_input("MACD signal", 2, 30, 9)
        pivot_delay = st.number_input("Pivot confirmation bars", 1, 10, 3)
        average_lines = st.multiselect(
            "차트 평균선",
            [f"ema_{i}" for i in (9, 20, 50, 100, 200)] + [f"sma_{i}" for i in (20, 60, 120, 200)],
            default=["ema_20", "ema_50", "ema_200"],
        )
        show_bands = st.checkbox("Bollinger bands", True)
    with st.expander("전략 · 리스크 설정"):
        min_score = st.slider("Minimum directional score", 50, 95, 65)
        min_quality = st.slider("Minimum signal quality", 50, 95, 75)
        min_rr = st.number_input("Minimum net average ladder RR", 0.5, 5.0, 1.5, step=0.1)
        atr_buffer = st.number_input("Stop ATR buffer", 0.1, 3.0, 0.5, step=0.1)
        entry_width = st.number_input("Entry half-width · ATR", 0.1, 1.0, 0.25, step=0.05)
        cooldown = st.number_input("Cooldown bars", 0, 100, 12)
        allow_short = st.checkbox("Short 연구·모의거래 허용", False)
        disabled_regimes = st.multiselect(
            "No Trade regimes",
            ["Strong Uptrend", "Uptrend", "Sideways", "Downtrend", "Strong Downtrend"],
            default=["Strong Downtrend"],
        )
        sideways_risk = st.slider("Sideways risk multiplier", 0.0, 1.0, 0.5, 0.1)
        daily_limit = st.slider("Daily loss limit %", 1.0, 10.0, 3.0)
        weekly_limit = st.slider("Weekly loss limit %", 2.0, 20.0, 6.0)
        max_dd = st.slider("Maximum drawdown %", 5.0, 40.0, 15.0)
        reduce_losses = st.number_input("Risk reduction after losses", 1, 10, 4)
        pause_losses = st.number_input("Pause after losses", 2, 15, 6)
        weights = {}
        for key, value in StrategyConfig().weights.items():
            weights[key] = st.number_input(f"{key.title()} weight", 0.0, 1.0, value, step=0.05)
    if PUBLIC:
        with st.expander("기록 보관 안내"):
            st.info(
                "모의거래·설정·결과는 현재 접속 세션에만 저장됩니다. "
                "새로고침·접속 종료·서버 재시작 후 유지되지 않을 수 있으니 필요한 결과를 다운로드하세요."
            )
    st.caption("공개 시장 데이터 · 실제 주문 기능 없음")

try:
    cfg = AppConfig(
        IndicatorConfig(
            ema_lengths=tuple(sorted(set((9, 20, 50, 100, 200, fast_ema)))),
            fast_trend_length=fast_ema,
            rsi_length=rsi_period,
            atr_length=atr_period,
            bb_length=bb_length,
            bb_std=bb_std,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            pivot_right=pivot_delay,
        ),
        StrategyConfig(
            weights=weights,
            min_score=min_score,
            min_quality=min_quality,
            min_rr=min_rr,
            atr_buffer=atr_buffer,
            entry_atr_width=entry_width,
            cooldown_bars=cooldown,
            allow_short=allow_short,
            disabled_regimes=tuple(disabled_regimes),
            regime_risk={"Sideways": sideways_risk, "Downtrend": 0.5},
        ),
        RiskConfig(
            capital=capital,
            risk_fraction=risk_pct / 100,
            fee=fee_pct / 100,
            slippage=slip_pct / 100,
            daily_loss_limit=daily_limit / 100,
            weekly_loss_limit=weekly_limit / 100,
            max_drawdown=max_dd / 100,
            reduce_after_losses=reduce_losses,
            pause_after_losses=pause_losses,
        ),
    )
    database = Database(DB_PATH)
except sqlite3.Error as exc:
    st.error(
        "기록을 열 수 없습니다. 잠시 후 새 접속에서 다시 시도하세요."
        if PUBLIC
        else f"데이터베이스를 열 수 없습니다: {exc}"
    )
    if not PUBLIC:
        st.info(
            "기존 DB 파일을 보존하고 BTC_DB_PATH를 확인하세요. 복구 전에는 다른 새 DB 경로를 사용할 수 있습니다."
        )
    st.stop()
except (ValueError, OSError) as exc:
    st.error(f"설정을 확인하세요: {exc}")
    st.stop()


@st.cache_data(ttl=3600, max_entries=6, show_spinner=False)
def get_demo(tf: str, count: int, quote_price: float) -> dict:
    return demo_bundle(tf, count, price=quote_price, include_macro=True)


@st.cache_data(ttl=30, max_entries=32, show_spinner=False)
def get_binance_quote(market: str) -> dict:
    try:
        return BinanceProvider().quote(market)
    except (DataError, ValueError, OSError, KeyError) as exc:
        # Briefly cache failures too, so each chart click cannot restart a slow request.
        return {"error": str(exc)}


@st.cache_data(ttl=60, max_entries=12, show_spinner=False)
def get_live_bundle(cache_path: str, market: str, pair: str, tf: str, start, end) -> dict:
    return DataService(cache_path).bundle(market, pair, tf, start, end, include_macro=True)


@st.fragment(run_every=60 if auto_refresh and not demo else None)
def dashboard() -> None:
    """Periodic live data refresh uses the same idempotent SQLite paper engine."""
    sequence = st.session_state.get("market_refresh_sequence", 0)
    refresh = sequence != st.session_state.get("market_refresh_consumed", 0)
    st.session_state["market_refresh_consumed"] = sequence
    try:
        if demo:
            bundle = get_demo(timeframe, bars, 90_000.0 if exchange == "Binance" else 130_000_000.0)
            start = bundle[timeframe].index[-bars]
        else:
            if len(date_range) != 2 or date_range[0] >= date_range[1]:
                st.info("시작일과 종료일을 선택하세요.")
                return
            start = pd.Timestamp(date_range[0], tz="UTC")
            end = min(
                pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1), pd.Timestamp.now(tz="UTC")
            )
            if PUBLIC:
                end = end.floor("min")
                if (end - start).total_seconds() / TIMEFRAMES[timeframe] > 3000:
                    st.info(
                        "공개 서버에서는 한 번에 최대 3,000개 봉을 분석합니다. 기간을 줄이거나 더 긴 Timeframe을 선택하세요."
                    )
                    return
            with st.spinner("공개 OHLCV 및 타임프레임별 워밍업 데이터 수집 중…"):
                smallest = min((*MTF_MAP[timeframe], *COMPOSITE_TIMEFRAMES), key=TIMEFRAMES.get)
                collection_end = candle_boundary(end, smallest)
                args = (str(runtime.market_cache), exchange, symbol, timeframe, start, collection_end)
                if refresh:
                    get_live_bundle.clear(*args)
                    bundle = DataService(runtime.market_cache).bundle(
                        exchange, symbol, timeframe, start, collection_end, refresh=True, include_macro=True
                    )
                else:
                    bundle = get_live_bundle(*args)
        research_bundle = {tf: bundle[tf] for tf in MTF_MAP[timeframe]}
        if any(df.empty for df in research_bundle.values()):
            st.error("필요한 타임프레임의 닫힌 봉을 받지 못했습니다. 시장·기간·네트워크 응답을 확인하세요.")
            return
        cutoff = candle_close(bundle["1h"].index[-1], "1h") if demo else end
        available_cutoff = cutoff
        cutoff = candle_boundary(cutoff, min(COMPOSITE_TIMEFRAMES, key=TIMEFRAMES.get))
        enriched = {
            tf: feature_frame(raw.loc[candle_close(raw.index, tf) <= available_cutoff], tf, cfg.indicators)
            for tf, raw in bundle.items()
            if not raw.empty
        }
        features, analysis = research_analysis(research_bundle, timeframe, cfg, enriched)
        combined = combined_analysis(bundle, cutoff, cfg, enriched)
        context = hashlib.sha256(
            dumps(
                [
                    SOURCE_VERSION,
                    cfg.to_dict(),
                    exchange,
                    symbol,
                    timeframe,
                    demo,
                    str(start),
                    str(features.index[-1]),
                ]
            ).encode()
        ).hexdigest()
        source_name = "demo" if demo else "live"
        trader = PaperTrader(database, cfg, exchange, symbol, timeframe, source_name)
        database.record_signal(analysis, exchange, symbol, timeframe, source_name, trader.strategy_key)
        composite_key = (
            "composite-v3-position:" + hashlib.sha256(dumps(cfg.to_dict()).encode()).hexdigest()[:16]
        )
        database.record_signal(combined, exchange, symbol, "ALL", source_name, composite_key)
    except (DataError, ValueError, OSError, KeyError, sqlite3.Error) as exc:
        logging.exception("Dashboard market data/analysis failed")
        st.error(f"데이터/분석 오류: {exc}")
        st.info(
            "네트워크 제한 시 Demo 모드로 계산·백테스트·UI를 사용할 수 있습니다. Live 오류를 합성 데이터로 대체하지 않습니다."
        )
        return
    paper_state = trader.state()
    if paper_state.get("enabled") or paper_state.get("position"):
        trader.tick(features, allow_new_entries=paper_state.get("enabled", False))
    confirmed_hour = bundle["1h"]
    displayed_price = float(confirmed_hour.close.iloc[-1])
    change = (
        float(confirmed_hour.close.iloc[-1] / confirmed_hour.close.iloc[-2] - 1) * 100
        if len(confirmed_hour) > 1
        else None
    )
    price_label = "합성 데이터 종가" if demo else "마지막 확정 봉 종가"
    change_label = "직전 확정 봉 대비"
    quote_note = ""
    if not demo and exchange == "Binance":
        try:
            if refresh:
                get_binance_quote.clear(symbol)
            current_quote = get_binance_quote(symbol)
            if "error" in current_quote:
                raise DataError(current_quote["error"])
            displayed_price = current_quote["price"]
            change = current_quote["change_24h"]
            change_label = "24시간 변동"
            observed = pd.Timestamp(current_quote["observed_at"]).tz_convert(display_timezone)
            price_label = f"현재가 · 최근 조회 {observed:%H:%M:%S}"
        except (DataError, ValueError, OSError, KeyError) as exc:
            logging.warning("Public Binance ticker unavailable: %s", exc)
            quote_note = "현재가 조회가 지연되어 마지막 확정 봉 종가를 표시합니다."
    confirmed = pd.Timestamp(combined.timestamp).tz_convert(display_timezone)
    st.markdown(
        market_hero(
            exchange=exchange,
            symbol=symbol,
            timeframe="5개 시간대 종합",
            quote=quote_currency,
            price=displayed_price,
            change=change,
            change_label=change_label,
            price_label=price_label,
            confirmed_at=f"{confirmed:%m.%d %H:%M} · {display_timezone}",
            demo=demo,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(decision_panel(combined), unsafe_allow_html=True)
    st.markdown(composite_cards(combined), unsafe_allow_html=True)
    if demo:
        st.warning("DEMO · 합성 가격으로 계산한 화면입니다. 실제 Binance 시세는 Live 모드에서 확인하세요.")
    if quote_note:
        st.caption(quote_note)
    st.caption(
        "수주~수개월 관점 · 가격 매력과 하락 진정을 함께 봐요. ‘가격 매력’은 기술적 상대 위치이며 적정 가치나 성공 확률이 아니에요."
    )
    if combined.action == "매수" and combined.plan:
        plan = combined.plan
        st.write(
            f"**{combined.mode} · 일봉 기준 진입 영역** · {plan.entry_low:,.2f} ~ {plan.entry_high:,.2f} {quote_currency}"
        )
        st.write(
            f"손절 {plan.stop:,.2f} · 목표 "
            + " / ".join(f"{value:,.2f}" for value in plan.targets)
            + f" {quote_currency}"
        )
        st.caption(
            "일봉 변동폭과 확정 지지점을 사용해요. 신호는 진입 영역 상단의 수수료·슬리피지 후 평균 RR까지 확인합니다. 진입 영역 안에서 분할 접근을 검토해요."
        )
    tabs = st.tabs(
        [
            "시장 개요",
            "기술 지표",
            "다중 시간대",
            "과거 유사성",
            "백테스트",
            "전략 검증",
            "몬테카를로",
            "모의거래",
            "신호 기록",
            "설정",
        ],
        key="dashboard_tab",
        on_change="rerun",
    )
    if tabs[0].open:
        with tabs[0]:
            st.markdown('<p class="btc-section-label">필요한 만큼, 자유롭게</p>', unsafe_allow_html=True)
            st.subheader("차트로 확인하기")
            chart_tf = st.segmented_control(
                "차트 시간대",
                COMPOSITE_TIMEFRAMES,
                default="1d",
                format_func=FRAME_LABELS.get,
                key="price_chart_timeframe",
            )
            chart_tf = chart_tf or "1d"
            chart_view = st.segmented_control("차트 보기", ["간편", "상세"], default="간편") or "간편"
            overlays = st.pills(
                "겹쳐 볼 지표",
                ["일목균형표", "이동평균선", "볼린저밴드", "가격 영역"],
                selection_mode="multi",
                default=["일목균형표"],
            )
            detailed_chart = chart_view == "상세"
            chart_bars = 120
            if detailed_chart:
                chart_bars = st.select_slider("표시할 봉 수", options=[60, 120, 240, 400], value=240)
            chart_raw = bundle.get(chart_tf)
            if chart_raw is not None and not chart_raw.empty:
                chart_features, chart_analysis = research_analysis(
                    {tf: bundle[tf] for tf in MTF_MAP[chart_tf] if tf in bundle and not bundle[tf].empty},
                    chart_tf,
                    cfg,
                    enriched,
                )
                st.plotly_chart(
                    price_chart(
                        chart_features.tail(420),
                        chart_analysis,
                        display_timezone,
                        tuple(average_lines) if "이동평균선" in overlays else (),
                        "볼린저밴드" in overlays,
                        quote=quote_currency,
                        ichimoku="일목균형표" in overlays,
                        ichimoku_detail=detailed_chart,
                        zones_visible="가격 영역" in overlays,
                        levels_visible="가격 영역" in overlays,
                        bars=chart_bars,
                    ),
                    width="stretch",
                    key="chart_01",
                    theme=None,
                    config={
                        "displaylogo": False,
                        "displayModeBar": detailed_chart,
                        "scrollZoom": False,
                        "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"]
                        if detailed_chart
                        else [],
                        "toImageButtonOptions": {"format": "png", "filename": "btc-signal-lab"},
                    },
                )
                st.caption(
                    f"{FRAME_LABELS[chart_tf]} · {len(chart_features):,}개 확정 봉. 이 차트의 관찰용 가격선은 종합 매수·매도 신호와 별개입니다."
                )
                if "일목균형표" in overlays:
                    st.caption(
                        "앞으로 그려진 일목 구름은 지금까지의 데이터로 계산한 표시 영역이에요. 미래 가격 예측이 아니에요."
                    )
                    st.subheader(f"일목균형표, 이렇게 읽어요 · {FRAME_LABELS[chart_tf]}")
                    st.markdown(
                        ichimoku_cards(
                            combined.frames[chart_tf].indicators,
                            displacement=cfg.indicators.ichimoku_displacement,
                        ),
                        unsafe_allow_html=True,
                    )
                    with st.expander("일목균형표 사용법"):
                        st.write(
                            "간편 보기에서는 구름을 먼저 확인해요. 상세 보기에서는 전환선·기준선·후행스팬을 함께 볼 수 있어요."
                        )
                        st.write(
                            "선행 구름은 지금까지의 고가·저가로 계산한 값을 미래 축에 옮겨 그린 영역이에요. 미래 가격 예측이 아니에요."
                        )
                        st.write(
                            "후행스팬은 현재 종가를 과거 축에 그려요. 신호는 현재 종가와 이미 확정된 과거 종가를 비교하므로 미래 가격을 참조하지 않아요."
                        )
                        st.write(
                            "일목 하나만으로 신호를 만들지 않고 기존 지표와 다섯 시간대의 조건을 함께 확인해요."
                        )
                if detailed_chart:
                    st.caption(
                        "상세 차트의 도구로 확대, 선·영역 그리기, 이미지 저장을 할 수 있어요. 그린 도형은 분석 신호를 바꾸지 않아요."
                    )
            else:
                st.info(
                    f"{FRAME_LABELS[chart_tf]} 데이터를 받지 못했습니다. 다중 시간대 탭에서 수집 상태를 확인하세요."
                )
            with st.expander("종합 판단의 전체 근거"):
                for reason in combined.reasons:
                    st.write(f"• {reason}")
            st.button("과거와 비슷한 차트 찾기", on_click=open_history_comparison)
            st.caption(f"아래 세부 근거·가격 영역은 연구 시간대 {timeframe} 기준입니다.")
            st.subheader("지금 주목할 근거")
            left, right = st.columns(2)
            with left.container(border=True):
                st.markdown("**상승을 뒷받침하는 요인**")
                for text in list(dict.fromkeys(analysis.score.positive))[:3]:
                    st.write(f"• {text}")
                if not analysis.score.positive:
                    st.caption("강한 상승 근거가 확인되지 않았습니다.")
            with right.container(border=True):
                st.markdown("**진입 전 확인할 위험**")
                for text in list(dict.fromkeys(analysis.reasons))[:3]:
                    st.write(f"• {text}")
                if not analysis.reasons:
                    st.caption("규칙상 추가 위험 요인이 없습니다. 시장 변동 위험은 남습니다.")
            with st.expander("세부 점수 · 분석 근거 전체"):
                score_columns = st.columns(5)
                for column, (name, value) in zip(score_columns, analysis.score.categories.items()):
                    column.metric(korean(name), f"{value:.1f}")
                st.write(analysis.narrative)
            if analysis.plan:
                p = analysis.plan
                st.subheader("진입 시나리오" if analysis.eligible else "관찰용 가격 영역")
                st.write(f"**진입 영역** {p.entry_low:,.2f} ~ {p.entry_high:,.2f} · **손절** {p.stop:,.2f}")
                st.dataframe(
                    pd.DataFrame({"Target": ["TP1", "TP2", "TP3"], "Price": p.targets, "Gross R": p.rr}),
                    hide_index=True,
                )
                size = position_size(
                    capital,
                    p.entry * (1 + (1 if p.direction == "long" else -1) * cfg.risk.slippage),
                    p.stop,
                    cfg.risk,
                    analysis.risk_multiplier,
                    p.direction,
                )
                st.write(
                    f"가상 수량 {size.quantity:.6f} BTC · 비용 포함 예상 손절 손실 {size.estimated_loss:,.2f} · 예산 {size.risk_budget:,.2f}"
                )
                st.caption(
                    "목표는 각각 1/3 청산. 표시 RR은 비용 전이며 실제 체결은 비용 후 평균 RR을 다시 검사합니다."
                )
    if tabs[1].open:
        with tabs[1]:
            st.subheader(f"일목균형표 · 연구 시간대 {timeframe}")
            st.markdown(
                ichimoku_cards(
                    features.iloc[-1].to_dict(), displacement=cfg.indicators.ichimoku_displacement
                ),
                unsafe_allow_html=True,
            )
            st.caption("전환선 9 · 기준선 26 · 선행스팬 B 52 · 표시 이동 26봉이 기본이에요.")
            st.subheader("모멘텀과 변동성")
            st.plotly_chart(
                indicator_chart(features, display_timezone), width="stretch", key="chart_02", theme=None
            )
            with st.expander("전체 지표 원본 값"):
                st.dataframe(features.drop(columns=["available_at"]).tail(100), width="stretch")
            with st.expander("데이터 품질 상세"):
                st.json({tf: df.attrs.get("quality", {}) for tf, df in bundle.items()})
    if tabs[2].open:
        with tabs[2]:
            st.subheader("다섯 시간대 통합 분석")
            rows = [
                {
                    "시간대": FRAME_LABELS[tf],
                    "상승 우위": round(frame.score, 1) if frame.ready else None,
                    "반영 비중": f"{FRAME_WEIGHTS[tf]:.0%}",
                    "연속 확정 봉": frame.bars,
                    "지표 충족": f"{frame.coverage:.0%}",
                    "상태": "반영" if frame.ready else "대기 / 미반영",
                    "시장 흐름": korean(frame.regime),
                    "변동성": korean(frame.volatility),
                    "확정 시각": str(pd.Timestamp(frame.confirmed_at).tz_convert(display_timezone))
                    if frame.confirmed_at
                    else "없음",
                }
                for tf, frame in combined.frames.items()
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.subheader("시간대별 전체 지표")
            indicator_rows = [
                {"시간대": FRAME_LABELS[tf], **frame.indicators} for tf, frame in combined.frames.items()
            ]
            st.dataframe(
                pd.DataFrame(indicator_rows).set_index("시간대").T.rename(index=LABELS),
                width="stretch",
            )
            st.caption(
                "빈칸은 이력이 부족해 계산할 수 없는 지표입니다. 월봉 EMA200·SMA200 등은 임의로 채우지 않습니다."
            )
            st.subheader("시간대별 지표 그룹 점수")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시간대": FRAME_LABELS[tf],
                            **{
                                korean(k): round(v, 1) if frame.ready else None
                                for k, v in frame.categories.items()
                            },
                        }
                        for tf, frame in combined.frames.items()
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            for tf, frame in combined.frames.items():
                if frame.notes:
                    with st.expander(f"{FRAME_LABELS[tf]} · 데이터 상태"):
                        for note in frame.notes:
                            st.write(note)
            st.caption(
                "주봉은 월요일 UTC 00:00, 월봉은 다음 달 1일 UTC 00:00에 확정됩니다. 미완성 봉은 제외합니다."
            )
            with st.expander("종합 신호 조건"):
                st.write(
                    "수주~수개월 관점: 1시간 5% · 4시간 10% · 일봉 40% · 주봉 30% · 월봉 15%. 단기 봉 상승은 매수의 필수 조건이 아니에요."
                )
                st.write(
                    "눌림목 매수: 중기 기준 대비 할인·고점 대비 조정·지지 접근과 하락 압력 둔화를 확인하고, 주봉·월봉 방향 및 일봉 비용 후 RR이 지지하면 분할매수를 검토해요."
                )
                st.write(
                    "매도: 일봉·주봉 하락이 함께 확인되면 현물 보유분 축소, 일봉 RSI와 가격 이격이 과열되면 분할 이익 실현 신호를 표시해요. 신규 숏 주문은 만들지 않아요."
                )
                st.write(
                    "급락·지지 이탈·거래량 부족은 신규 매수를 보류해요. 다섯 시간대의 핵심 지표가 부족하면 판단을 보류해요. 가격 매력은 기술적 상대 위치이며 적정 가치나 수익 확률이 아니에요."
                )
            st.download_button(
                "종합 분석 JSON 다운로드",
                dumps(combined),
                "composite-analysis.json",
                "application/json",
            )
    if tabs[3].open:
        with tabs[3]:
            from btc_analyzer.ui.history_view import render_history_view

            render_history_view(
                cache_path=str(runtime.market_cache),
                exchange=exchange,
                symbol=symbol,
                cutoff=available_cutoff,
                demo=demo,
                demo_frames=bundle,
                timezone=display_timezone,
                refresh=refresh,
            )
    if tabs[4].open:
        with tabs[4]:
            st.caption(
                f"이 탭은 연구 시간대 {timeframe}의 지표 전략을 검증합니다. 상단의 새 종합 신호에 대한 성과 검증 결과는 아닙니다."
            )
            if st.button("백테스트 실행", type="primary"):
                from btc_analyzer.backtest.engine import BacktestEngine

                try:
                    with (
                        research_gate().job(),
                        st.spinner("다음 봉 시가 체결과 비용·리스크 보호를 적용하는 중…"),
                    ):
                        result = BacktestEngine(cfg).run(research_bundle, timeframe, start=start)
                        run_id = database.save_backtest(result, exchange, symbol, timeframe, source_name)
                        st.session_state["backtest_result"] = (context, result, run_id)
                except ResearchBusy as exc:
                    st.info(str(exc))
            item = st.session_state.get("backtest_result")
            if item and item[0] == context:
                result = item[1]
                st.caption(f"백테스트 결과 #{item[2]}")
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Metric": list(result.metrics),
                            "Value": [str(v) for v in result.metrics.values()],
                        }
                    ),
                    hide_index=True,
                )
                for warning in result.warnings:
                    st.warning(warning)
                st.plotly_chart(
                    equity_chart(result.equity, quote_currency),
                    width="stretch",
                    key="chart_03",
                    theme=None,
                )
                st.plotly_chart(
                    price_chart(
                        features,
                        analysis,
                        display_timezone,
                        tuple(average_lines),
                        show_bands,
                        result.trades,
                        quote_currency,
                    ),
                    width="stretch",
                    key="chart_04",
                    theme=None,
                )
                st.dataframe(result.trades.drop(columns=["exits"], errors="ignore"), width="stretch")
                st.dataframe(result.regimes, hide_index=True)
                st.caption(
                    "Regime 표는 진입 시점 기준 거래 집단입니다. 변동성 집단과 추세 집단은 중복될 수 있습니다."
                )
                monthly = result.equity.equity.resample("ME").last().pct_change(fill_method=None).dropna()
                if len(monthly):
                    import plotly.express as px

                    st.plotly_chart(
                        px.bar(
                            x=monthly.index,
                            y=monthly * 100,
                            labels={"x": "Month", "y": "Return %"},
                        ),
                        width="stretch",
                        key="chart_05",
                    )
                st.download_button(
                    "거래 CSV 다운로드",
                    result.trades.to_csv(index=False),
                    "backtest_trades.csv",
                    "text/csv",
                )
            else:
                st.info("백테스트를 실행하면 순자산·Buy & Hold·낙폭·거래 체결 결과가 표시됩니다.")
    if tabs[5].open:
        with tabs[5]:
            st.caption(
                f"연구 시간대 {timeframe}의 지표 전략 검증입니다. 새 종합 신호의 성과를 검증한 결과는 아닙니다."
            )
            st.write(
                "IS 60% / Validation 20% / OOS 20% · IS 내 주변 파라미터 · 비용 1x/1.5x/2x · Walk Forward"
            )
            compact = st.checkbox("빠른 검증 · ATR 3개 조합 (해제: RSI×EMA×ATR 27개)", PUBLIC)
            if st.button("전략 안정성 검증 실행"):
                from btc_analyzer.backtest.robustness import run_robustness

                try:
                    if PUBLIC and int((features.index >= start).sum()) > 1200:
                        raise ValueError(
                            "공개 서버의 안정성 검증은 최대 1,200개 평가 봉을 사용합니다. 평가 기간을 줄여 다시 실행하세요."
                        )
                    with (
                        research_gate().job(),
                        st.spinner("분리된 평가 기간과 파라미터 주변을 검증하는 중…"),
                    ):
                        report = run_robustness(research_bundle, timeframe, cfg, start, compact=compact)
                    st.session_state["robustness_report"] = (context, report)
                except ValueError as exc:
                    st.error(str(exc))
                except ResearchBusy as exc:
                    st.info(str(exc))
            report_item = st.session_state.get("robustness_report")
            if report_item and report_item[0] == context:
                report = report_item[1]
                st.json(report["assessment"])
                st.dataframe(
                    pd.DataFrame(
                        [{"Period": name, **result.metrics} for name, result in report["splits"].items()]
                    ),
                    hide_index=True,
                )
                st.write("**Parameter sensitivity (IS only)**")
                st.dataframe(report["parameters"], hide_index=True)
                if len(report["parameters"]):
                    import plotly.express as px

                    st.plotly_chart(
                        px.scatter(
                            report["parameters"],
                            x="atr_buffer",
                            y="return",
                            color="rsi",
                            symbol="ema",
                            hover_data=["trades", "mdd"],
                        ),
                        width="stretch",
                        key="chart_06",
                    )
                st.write("**Trading cost stress**")
                st.dataframe(report["costs"], hide_index=True)
                st.write("**Walk-forward folds**")
                st.dataframe(
                    report["walk_forward"].drop(columns=["selected_settings"], errors="ignore"),
                    hide_index=True,
                )
            st.caption(
                "Production Candidate는 연구 평가 이름입니다. V1에서 실제 주문을 활성화하지 않습니다. 거래가 없는 결과는 검증 통과로 취급하지 않습니다."
            )
    if tabs[6].open:
        with tabs[6]:
            count = st.number_input("Simulations", 1000, 5000 if PUBLIC else 20000, 1000, 1000)
            seed = st.number_input("Seed", 0, 1_000_000, 42)
            if st.button("Monte Carlo 실행"):
                from btc_analyzer.backtest.monte_carlo import monte_carlo

                current_result = st.session_state.get("backtest_result")
                if not current_result or current_result[0] != context:
                    st.info("현재 설정으로 백테스트를 먼저 실행하세요.")
                else:
                    try:
                        with research_gate().job():
                            mc = monte_carlo(
                                current_result[1].trades,
                                capital,
                                risk_pct / 100,
                                count,
                                seed,
                            )
                            st.session_state["monte_carlo_result"] = (context, mc)
                    except ResearchBusy as exc:
                        st.info(str(exc))
            mc_item = st.session_state.get("monte_carlo_result")
            if mc_item and mc_item[0] == context:
                mc = mc_item[1]
                if not mc["available"]:
                    st.warning("완료된 거래가 없어 Monte Carlo를 계산할 수 없습니다.")
                else:
                    import plotly.express as px

                    st.json({k: v for k, v in mc.items() if k not in ("equity_bands", "drawdowns")})
                    if mc.get("evidence_warning"):
                        st.warning(mc["evidence_warning"])
                    st.plotly_chart(
                        monte_chart(mc["equity_bands"], quote_currency),
                        width="stretch",
                        key="chart_07",
                        theme=None,
                    )
                    st.plotly_chart(
                        px.histogram(x=mc["drawdowns"] * 100, labels={"x": "Maximum drawdown %"}),
                        width="stretch",
                        key="chart_08",
                    )
            st.caption(
                "수수료를 반영한 거래 R을 복원 추출합니다. 미관측 시장·유동성·상관 변화에 대한 보장은 제공하지 않습니다."
            )
    if tabs[7].open:
        with tabs[7]:
            st.caption(
                f"모의거래는 연구 시간대 {timeframe}의 지표 전략으로 동작합니다. 상단 종합 신호와 별도입니다."
            )
            st.write(
                "실제 돈이나 주문 API를 사용하지 않습니다. 활성화 이후 닫힌 봉만 가상 체결하며 새 계정의 과거 거래를 만들지 않습니다."
            )
            enabled = trader.state().get("enabled", False)
            c1, c2, c3 = st.columns(3)
            if c1.button("모의거래 활성화"):
                trader.set_enabled(True)
                trader.tick(features)
                enabled = True
            if c2.button("신규 모의거래 중지"):
                trader.set_enabled(False)
                enabled = False
            if c3.button("리스크 보호 명시적 리셋"):
                trader.reset_protection()
            st.write(f"현재 상태: {'활성' if enabled else '중지'}")
            state = trader.state()
            with st.expander("모의계좌 상세 상태"):
                st.json({k: v for k, v in state.items() if k not in ("guard", "gate")})
            st.dataframe(
                database.history("paper_trades", account=trader.account).drop(
                    columns=["payload"], errors="ignore"
                ),
                hide_index=True,
            )
            st.caption(
                "수동 새로고침 또는 Live 자동 업데이트로 진행합니다. 설정·거래소·시장·데이터 모드 변경 시 별도 계정을 사용합니다."
            )
    if tabs[8].open:
        with tabs[8]:
            history = database.history("signals")
            if not history.empty:
                history = history[
                    (history.exchange == exchange)
                    & (history.symbol == symbol)
                    & (history.timeframe.isin([timeframe, "ALL"]))
                    & (history.data_source == source_name)
                ]
            st.dataframe(
                history.drop(columns=["payload"], errors="ignore"),
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "신호 CSV 다운로드",
                history.to_csv(index=False),
                "signals.csv",
                "text/csv",
            )
            st.write("**저장된 백테스트**")
            st.dataframe(
                database.history("backtest_runs").drop(columns=["equity", "settings"], errors="ignore"),
                hide_index=True,
            )
    if tabs[9].open:
        with tabs[9]:
            with st.expander("현재 설정 상세"):
                st.json(cfg.to_dict())
            if st.button("현재 설정 SQLite에 저장"):
                database.save_settings("default", cfg.to_dict())
                st.success("설정을 저장했습니다.")
            st.download_button(
                "설정 JSON 다운로드",
                dumps(cfg.to_dict()),
                "strategy.json",
                "application/json",
            )
            uploaded = st.file_uploader("설정 JSON 검증/저장", type=["json"])
            if uploaded is not None:
                try:
                    import json

                    loaded = AppConfig.from_dict(json.load(uploaded))
                    st.json(loaded.to_dict())
                    if st.button("업로드 설정 저장"):
                        database.save_settings("imported", loaded.to_dict())
                        st.success(
                            "imported 설정으로 저장했습니다. CLI에서 strategy.json으로 재현하거나 사이드바에 적용하세요."
                        )
                except (ValueError, TypeError) as exc:
                    st.error(f"설정 오류: {exc}")
            st.caption("비밀키는 저장하거나 읽지 않습니다. 공개 OHLCV는 API 키가 필요 없습니다.")


dashboard()
