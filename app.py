"""Streamlit BTC research dashboard. V1 has no live-order code or credentials."""

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from btc_analyzer.config import AppConfig, IndicatorConfig, StrategyConfig, RiskConfig, TIMEFRAMES
from btc_analyzer.data.service import DataService, demo_bundle
from btc_analyzer.data.base_provider import DataError
from btc_analyzer.analysis.multi_timeframe import prepare, enrich
from btc_analyzer.backtest.engine import BacktestEngine
from btc_analyzer.backtest.robustness import run_robustness
from btc_analyzer.backtest.monte_carlo import monte_carlo
from btc_analyzer.risk.position_sizing import position_size
from btc_analyzer.paper.paper_trading import PaperTrader
from btc_analyzer.storage.database import Database, dumps
from btc_analyzer.strategy.signal_engine import analyze
from btc_analyzer.ui.charts import price_chart, indicator_chart, equity_chart, monte_chart
from btc_analyzer.ui.web_runtime import ResearchBusy, ResearchGate, runtime_paths

load_dotenv(override=False)
logging.basicConfig(level=os.getenv("BTC_LOG_LEVEL", "INFO"))
st.set_page_config(page_title="BTC 분석 대시보드", page_icon="₿", layout="wide")
st.title("₿ BTC Trading Analyzer")
st.caption("BTC 시장 분석 · 백테스트 · 모의거래 · 신호 기록 | 실제 주문 기능 없음")
app_environment = dict(os.environ)
if globals().get("PUBLIC_DEPLOYMENT"):
    app_environment["BTC_APP_MODE"] = "public"
    app_environment.setdefault("BTC_DEFAULT_EXCHANGE", "Upbit")
    app_environment.setdefault("BTC_DEFAULT_SOURCE", "live")
try:
    runtime = runtime_paths(st.session_state, app_environment)
except OSError:
    st.error("저장 공간을 준비할 수 없습니다. 서버의 저장 공간과 쓰기 권한을 확인하세요.")
    st.stop()
PUBLIC = runtime.public
DB_PATH = runtime.database
if PUBLIC:
    st.info(
        "모의거래·설정·결과는 현재 접속 세션에만 저장됩니다. "
        "새로고침·접속 종료·서버 재시작 후 유지되지 않을 수 있으니 필요한 결과를 다운로드하세요."
    )


@st.cache_resource
def research_gate() -> ResearchGate:
    return ResearchGate()


with st.sidebar:
    st.header("시장 / 데이터")
    source = st.selectbox(
        "데이터 모드",
        ["Demo · 합성 데이터", "Live · 공개 거래소 데이터"],
        index=int(app_environment.get("BTC_DEFAULT_SOURCE", "demo").lower() == "live"),
    )
    demo = source.startswith("Demo")
    exchange = st.selectbox(
        "Exchange", ["Binance", "Upbit"], index=int(app_environment.get("BTC_DEFAULT_EXCHANGE") == "Upbit")
    )
    symbol = st.text_input(
        "Symbol", "BTC/USDT" if exchange == "Binance" else "KRW-BTC", key=f"symbol_{exchange}"
    )
    timeframe = st.selectbox("Timeframe", list(TIMEFRAMES), index=2)
    display_timezone = st.selectbox("표시 시간대", ["Asia/Seoul", "UTC", "America/New_York"])
    today = datetime.now(timezone.utc).date()
    date_range = st.date_input("Date Range · Live", (today - timedelta(days=7 if PUBLIC else 30), today))
    bars = st.slider("Demo 평가 봉 수", 400, 1200 if PUBLIC else 2400, 800, 100, disabled=not demo)
    refresh = st.button("데이터 새로고침")
    auto_refresh = st.checkbox("Live 자동 업데이트 · 60초", value=False, disabled=demo)
    st.header("계좌 / 비용")
    capital = st.number_input(
        "Capital · USDT / KRW",
        min_value=100.0,
        value=10_000.0 if exchange == "Binance" else 10_000_000.0,
        step=100.0,
    )
    risk_pct = st.number_input("Account Risk %", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
    fee_pct = st.number_input("Fee %", min_value=0.0, max_value=5.0, value=0.1, step=0.01)
    slip_pct = st.number_input("Slippage %", min_value=0.0, max_value=5.0, value=0.05, step=0.01)
    st.caption("레버리지 1x · 통화는 선택 시장의 호가 통화")
    with st.expander("Indicator Settings"):
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
    with st.expander("Strategy / Risk Settings"):
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


@st.cache_data(ttl=60, show_spinner=False)
def get_demo(tf: str, count: int, quote_price: float) -> dict:
    return demo_bundle(tf, count, price=quote_price)


@st.fragment(run_every=60 if auto_refresh and not demo else None)
def dashboard() -> None:
    """Periodic live data refresh uses the same idempotent SQLite paper engine."""
    try:
        if demo:
            st.warning(
                "DEMO · 모든 가격·거래량은 재현 가능한 합성 데이터입니다. 실제 BTC 시장 분석 결과가 아닙니다."
            )
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
                bundle = DataService(runtime.market_cache, ttl=45 if auto_refresh else 300).bundle(
                    exchange, symbol, timeframe, start, end, refresh=refresh
                )
        if any(df.empty for df in bundle.values()):
            st.error("필요한 타임프레임의 닫힌 봉을 받지 못했습니다. 시장·기간·네트워크 응답을 확인하세요.")
            return
        features = prepare(bundle, timeframe, cfg)
        analysis = analyze(features, cfg)
        context = hashlib.sha256(
            dumps(
                [cfg.to_dict(), exchange, symbol, timeframe, demo, str(start), str(features.index[-1])]
            ).encode()
        ).hexdigest()
        source_name = "demo" if demo else "live"
        trader = PaperTrader(database, cfg, exchange, symbol, timeframe, source_name)
        database.record_signal(analysis, exchange, symbol, timeframe, source_name, trader.strategy_key)
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
    metrics = st.columns(5)
    metrics[0].metric(f"{symbol} · Current Price", f"{features.close.iloc[-1]:,.2f}")
    metrics[1].metric("Overall Score", f"{analysis.score.overall:.1f} / 100", analysis.score.label)
    metrics[2].metric("Signal Quality", f"{analysis.quality:.1f} / 100", analysis.quality_label)
    metrics[3].metric("Market Regime", analysis.regime)
    metrics[4].metric("현재 후보", analysis.direction.upper() if analysis.eligible else "No Trade")
    st.caption(
        f"마지막 확정 봉: {features.index[-1].tz_convert(display_timezone)} · Confidence {analysis.confidence} (규칙 기반 품질, 성공 확률 아님)"
    )
    tabs = st.tabs(
        [
            "Overview",
            "Indicators",
            "Multi-Timeframe",
            "Backtest",
            "Robustness",
            "Monte Carlo",
            "Paper Trading",
            "Signal History",
            "Settings",
        ]
    )
    with tabs[0]:
        st.plotly_chart(
            price_chart(features, analysis, display_timezone, tuple(average_lines), show_bands),
            width="stretch",
            key="chart_01",
        )
        st.write(analysis.narrative)
        score_columns = st.columns(5)
        for column, (name, value) in zip(score_columns, analysis.score.categories.items()):
            column.metric(name.title(), f"{value:.1f}")
        left, right = st.columns(2)
        left.write("**Positive Factors**")
        for text in analysis.score.positive:
            left.write(f"+ {text}")
        right.write("**Risk Factors**")
        for text in analysis.reasons:
            right.write(f"• {text}")
        if analysis.plan:
            p = analysis.plan
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
    with tabs[1]:
        st.plotly_chart(indicator_chart(features, display_timezone), width="stretch", key="chart_02")
        st.dataframe(features.drop(columns=["available_at"]).tail(100), width="stretch")
        st.json({tf: df.attrs.get("quality", {}) for tf, df in bundle.items()})
    with tabs[2]:
        rows = []
        for tf, raw in bundle.items():
            f = enrich(raw, tf, cfg)
            r = f.iloc[-1]
            role = (
                "Current"
                if tf == timeframe
                else "Macro"
                if tf == "1d"
                else "Higher"
                if TIMEFRAMES[tf] > TIMEFRAMES[timeframe]
                else "Lower"
            )
            rows.append(
                {
                    "Role": role,
                    "Timeframe": tf,
                    "Regime": r.regime,
                    "Structure": r.structure,
                    "Volatility": r.volatility_regime,
                    "Close": r.close,
                    "RSI": r.rsi,
                    "Confirmed at (UTC)": str(f.index[-1] + pd.Timedelta(seconds=TIMEFRAMES[tf])),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.write(
            f"상위 추세 합의: {features.higher_trend.iloc[-1]:+.2f} · 가용 상위 데이터 {features.higher_coverage.iloc[-1]:.0%}"
        )
        st.caption(
            "상위 봉은 닫힌 시각부터 사용합니다. 가중치는 기간 비율의 제곱근으로 상위 타임프레임에 더 크게 적용합니다."
        )
        if features.higher_trend.iloc[-1] > 0.3 and features.price_change.iloc[-1] < 0:
            st.info("Bullish Trend + Short-Term Pullback: 상위 상승 추세 속 단기 조정입니다.")
    with tabs[3]:
        if st.button("백테스트 실행", type="primary"):
            try:
                with research_gate().job(), st.spinner("다음 봉 시가 체결과 비용·리스크 보호를 적용하는 중…"):
                    result = BacktestEngine(cfg).run(bundle, timeframe, start=start)
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
                    {"Metric": list(result.metrics), "Value": [str(v) for v in result.metrics.values()]}
                ),
                hide_index=True,
            )
            for warning in result.warnings:
                st.warning(warning)
            st.plotly_chart(equity_chart(result.equity), width="stretch", key="chart_03")
            st.plotly_chart(
                price_chart(
                    features, analysis, display_timezone, tuple(average_lines), show_bands, result.trades
                ),
                width="stretch",
                key="chart_04",
            )
            st.dataframe(result.trades.drop(columns=["exits"], errors="ignore"), width="stretch")
            st.dataframe(result.regimes, hide_index=True)
            st.caption(
                "Regime 표는 진입 시점 기준 거래 집단입니다. 변동성 집단과 추세 집단은 중복될 수 있습니다."
            )
            monthly = result.equity.equity.resample("ME").last().pct_change(fill_method=None).dropna()
            if len(monthly):
                st.plotly_chart(
                    px.bar(x=monthly.index, y=monthly * 100, labels={"x": "Month", "y": "Return %"}),
                    width="stretch",
                    key="chart_05",
                )
            st.download_button(
                "거래 CSV 다운로드", result.trades.to_csv(index=False), "backtest_trades.csv", "text/csv"
            )
        else:
            st.info("백테스트를 실행하면 순자산·Buy & Hold·낙폭·거래 체결 결과가 표시됩니다.")
    with tabs[4]:
        st.write("IS 60% / Validation 20% / OOS 20% · IS 내 주변 파라미터 · 비용 1x/1.5x/2x · Walk Forward")
        compact = st.checkbox("빠른 검증 · ATR 3개 조합 (해제: RSI×EMA×ATR 27개)", PUBLIC)
        if st.button("전략 안정성 검증 실행"):
            try:
                if PUBLIC and int((features.index >= start).sum()) > 1200:
                    raise ValueError(
                        "공개 서버의 안정성 검증은 최대 1,200개 평가 봉을 사용합니다. 평가 기간을 줄여 다시 실행하세요."
                    )
                with research_gate().job(), st.spinner("분리된 평가 기간과 파라미터 주변을 검증하는 중…"):
                    report = run_robustness(bundle, timeframe, cfg, start, compact=compact)
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
                report["walk_forward"].drop(columns=["selected_settings"], errors="ignore"), hide_index=True
            )
        st.caption(
            "Production Candidate는 연구 평가 이름입니다. V1에서 실제 주문을 활성화하지 않습니다. 거래가 없는 결과는 검증 통과로 취급하지 않습니다."
        )
    with tabs[5]:
        count = st.number_input("Simulations", 1000, 5000 if PUBLIC else 20000, 1000, 1000)
        seed = st.number_input("Seed", 0, 1_000_000, 42)
        if st.button("Monte Carlo 실행"):
            current_result = st.session_state.get("backtest_result")
            if not current_result or current_result[0] != context:
                st.info("현재 설정으로 백테스트를 먼저 실행하세요.")
            else:
                try:
                    with research_gate().job():
                        mc = monte_carlo(current_result[1].trades, capital, risk_pct / 100, count, seed)
                        st.session_state["monte_carlo_result"] = (context, mc)
                except ResearchBusy as exc:
                    st.info(str(exc))
        mc_item = st.session_state.get("monte_carlo_result")
        if mc_item and mc_item[0] == context:
            mc = mc_item[1]
            if not mc["available"]:
                st.warning("완료된 거래가 없어 Monte Carlo를 계산할 수 없습니다.")
            else:
                st.json({k: v for k, v in mc.items() if k not in ("equity_bands", "drawdowns")})
                if mc.get("evidence_warning"):
                    st.warning(mc["evidence_warning"])
                st.plotly_chart(monte_chart(mc["equity_bands"]), width="stretch", key="chart_07")
                st.plotly_chart(
                    px.histogram(x=mc["drawdowns"] * 100, labels={"x": "Maximum drawdown %"}),
                    width="stretch",
                    key="chart_08",
                )
        st.caption(
            "수수료를 반영한 거래 R을 복원 추출합니다. 미관측 시장·유동성·상관 변화에 대한 보장은 제공하지 않습니다."
        )
    with tabs[6]:
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
    with tabs[7]:
        history = database.history("signals")
        if not history.empty:
            history = history[
                (history.exchange == exchange)
                & (history.symbol == symbol)
                & (history.timeframe == timeframe)
                & (history.data_source == source_name)
            ]
        st.dataframe(history.drop(columns=["payload"], errors="ignore"), hide_index=True, width="stretch")
        st.download_button("신호 CSV 다운로드", history.to_csv(index=False), "signals.csv", "text/csv")
        st.write("**저장된 백테스트**")
        st.dataframe(
            database.history("backtest_runs").drop(columns=["equity", "settings"], errors="ignore"),
            hide_index=True,
        )
    with tabs[8]:
        st.json(cfg.to_dict())
        if st.button("현재 설정 SQLite에 저장"):
            database.save_settings("default", cfg.to_dict())
            st.success("설정을 저장했습니다.")
        st.download_button("설정 JSON 다운로드", dumps(cfg.to_dict()), "strategy.json", "application/json")
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
