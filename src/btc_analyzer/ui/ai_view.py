"""Explicit, cached OpenAI price scenarios, isolated from chart/validated models."""

from datetime import datetime, timezone, timedelta
from hashlib import sha256
from html import escape
import json
import math
import os
import re

import numpy as np
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from btc_analyzer.analysis.ai_forecast import AIService, forecast_key
from btc_analyzer.assets import price_text
from btc_analyzer.ui.market_context import current_context


def settings():
    key = os.getenv("BTC_AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("BTC_AI_MODEL", "gpt-4.1-mini")
    try:
        if not key:
            key = st.secrets.get("BTC_AI_API_KEY", st.secrets.get("OPENAI_API_KEY", ""))
        model = st.secrets.get("BTC_AI_MODEL", model)
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        pass
    if not isinstance(key, str) or any(c in key for c in "\r\n"):
        key = ""
    if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", model):
        model = "gpt-4.1-mini"
    return key.strip(), model


@st.cache_resource(max_entries=2, show_spinner=False, on_release=lambda value: value.close())
def ai_service(model, credential_tag, _api_key):
    return AIService(_api_key, model)


def public_facts(result, quote, period, asset_code, context_values):
    history, prediction = result.history, result.prediction
    evidence = [
        {
            "id": "model",
            "kind": "기술 모델",
            "center": prediction.center[-1],
            "low": prediction.lower[-1],
            "high": prediction.upper[-1],
            "validated_cases": len(result.validation),
            "mae": result.mae,
        },
        {
            "id": "indicators",
            "kind": "확정 봉 지표",
            "values": {
                k: float(v)
                for k, v in (context_values or {}).items()
                if isinstance(v, (float, int)) and math.isfinite(v)
            },
        },
        {
            "id": "analogues",
            "kind": "완료된 과거 사례",
            "matches": [
                {
                    "start": str(m.start),
                    "end": str(m.end),
                    "similarity": m.similarity,
                    "forward_return": m.forward_return,
                }
                for m in history.matches[:5]
            ],
        },
    ]
    now = datetime.now(timezone.utc)
    context = current_context().for_asset(asset_code)
    for i, item in enumerate(context.news(now, fresh_only=True)[:4]):
        evidence.append(
            {
                "id": f"news_{i}",
                "kind": "관련 기사 제목 · 내용은 미검증",
                "title": item.title[:250],
                "at": item.published_at.isoformat(),
                "source": item.source,
            }
        )
    for feed in context.feeds:
        value = feed.value
        if (
            hasattr(value, "price")
            and hasattr(value, "as_of")
            and not feed.error
            and timedelta(0) <= now - value.as_of <= timedelta(minutes=30)
        ):
            evidence.append(
                {
                    "id": "macro_" + feed.key,
                    "kind": "대외 시세",
                    "symbol": value.symbol,
                    "price": value.price,
                    "at": value.as_of.isoformat(),
                    "delay_minutes": value.delay_minutes,
                }
            )
    from btc_analyzer.ui.correction_view import calendar_service
    from btc_analyzer import __checkout_signature__

    calendar = calendar_service(__checkout_signature__).snapshot().feed("calendar")
    if (
        calendar.value
        and calendar.updated_at
        and not calendar.error
        and timedelta(0) <= now - calendar.updated_at <= timedelta(hours=2)
    ):
        for i, event in enumerate(e for e in calendar.value if e.at >= now):
            if i >= 3:
                break
            evidence.append(
                {
                    "id": f"calendar_{i}",
                    "kind": "예정 경제 발표 · 실제 결과 미정",
                    "title": event.title,
                    "at": event.at.isoformat(),
                    "consensus": event.forecast,
                    "previous": event.previous,
                }
            )
    return {
        "asset": asset_code,
        "quote": quote,
        "period": period,
        "origin": history.query_end.isoformat(),
        "target_date": prediction.dates[-1].isoformat(),
        "anchor": history.anchor_price,
        "evidence": evidence[:16],
    }


def overlay_payload(result, report, asset_code):
    base = np.asarray(result.prediction.center)
    progress = np.linspace(0, 1, len(base))
    paths = {
        name: (base * np.exp(np.log(price / base[-1]) * progress)).tolist()
        for name, price in (("center", report.target), ("lower", report.low), ("upper", report.high))
    }
    return {
        "asset": asset_code,
        "baseAt": int(result.prediction.dates[0].timestamp() * 1000),
        "count": len(base),
        "created": report.created_at,
        "basis": forecast_key(result),
        **paths,
    }


def render_ai_analysis(result, quote, period, asset_code, context_values):
    """Publish context to the sibling poller; never create nested timers."""
    st.session_state["_btc_ai_context"] = (result, quote, period, asset_code, context_values)
    key, _ = settings()
    if not key:
        st.markdown("#### AI 가격 분석")
        st.info(
            "OpenAI 연결 대기 · 운영자가 API 키를 등록하면 AI의 예상 가격대와 해석을 추가로 볼 수 있어요."
        )


@st.fragment(run_every=2)
def render_ai_panel():
    context = st.session_state.get("_btc_ai_context")
    if (
        not context
        or st.session_state.get("dashboard_tab") != "미래 예측"
        or st.session_state.get("analysis_asset", "BTC") != context[3]
        or st.session_state.get("prediction_mode", "예측 경로") != "예측 경로"
    ):
        return
    from btc_analyzer.analysis.forecast import HORIZON_LABELS

    horizon = st.session_state.get("forecast_horizon", "1mo")
    if horizon in HORIZON_LABELS and HORIZON_LABELS[horizon] != context[2]:
        return
    key, model = settings()
    if not key:
        return
    st.markdown("#### AI 가격 분석")
    render_connected_ai(*context, key, model)


def render_connected_ai(result, quote, period, asset_code, context_values, key, model):
    service = ai_service(model, sha256(key.encode()).hexdigest()[:16], key)
    context_key = f"ai_request_{asset_code}_{result.history.query_end.isoformat()}_{result.history.timeframe}_{result.history.forward}_{forecast_key(result)}_{model}"
    request_key = st.session_state.get(context_key)
    state = service.snapshot(request_key) if request_key else None
    if st.button(
        "AI 분석 다시 요청" if request_key else "AI로 가격대 분석",
        disabled=bool(state and state.loading),
        key="request_ai_forecast",
    ):
        try:
            request_key = service.submit(public_facts(result, quote, period, asset_code, context_values))
            st.session_state[context_key] = request_key
            state = service.snapshot(request_key)
        except ValueError as exc:
            st.info(str(exc))
    st.caption(
        f"{model} · 버튼을 눌렀을 때만 요청 · 공개 지표·유사 사례·관련 뉴스/대외 시세를 전송 · API 사용량이 발생할 수 있어요."
    )
    if not state:
        return
    if state.loading:
        st.info("AI가 근거와 예상 가격대를 검토하고 있어요. 차트는 계속 조작할 수 있습니다.")
        return
    if state.error:
        st.info(state.error)
        return
    value = state.report
    st.markdown(
        f'<article class="btc-ai-card"><span>AI 도착 가격 가정 · {escape(period)}</span><strong>{price_text(value.target)} {escape(quote)}</strong><p>범위 {price_text(value.low)} ~ {price_text(value.high)} {escape(quote)}</p><p>{escape(value.summary)}</p></article>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<ul class="btc-ai-reasons">'
        + "".join(f"<li>{escape(reason)}</li>" for reason in value.reasons)
        + "</ul>",
        unsafe_allow_html=True,
    )
    with st.expander("AI 가정의 위험과 무효 조건"):
        for risk in value.risks:
            st.markdown(f"<p>{escape(risk)}</p>", unsafe_allow_html=True)
        st.markdown(f"<p><b>무효 조건</b> {escape(value.invalidation)}</p>", unsafe_allow_html=True)
        names = {"model": "기술 모델", "indicators": "확정 봉 지표", "analogues": "과거 유사 사례"}
        st.caption(
            "검토 근거: "
            + " · ".join(
                dict.fromkeys(
                    names.get(
                        item,
                        "관련 기사"
                        if item.startswith("news_")
                        else "예정 경제 발표"
                        if item.startswith("calendar_")
                        else "대외 시장",
                    )
                    for item in value.evidence_ids
                )
            )
        )
    stamp = datetime.fromisoformat(value.created_at).astimezone(timezone.utc).strftime("%m.%d %H:%M UTC")
    st.caption(
        f"AI 분석 {stamp} · 봉 기준 {result.history.query_end.isoformat()} · AI 가격은 검증된 확률/오차 범위가 아닌 별도 가정이에요."
    )
    payload = escape(
        json.dumps(overlay_payload(result, value, asset_code), separators=(",", ":"), allow_nan=False),
        quote=True,
    )
    st.markdown(
        f'<span id="btc-ai-forecast" data-scenario="{payload}" hidden></span>', unsafe_allow_html=True
    )
    st.caption(
        "보라색 AI 경로는 AI의 도착 가격까지 기존 기술 모델 경로를 연결한 가정이며, AI가 매일의 가격을 예측했다는 뜻은 아니에요."
    )
