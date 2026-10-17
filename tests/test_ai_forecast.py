"""Real protocol shapes, bounded failure, deduplication and honest missing credentials."""

import json
from threading import Event
import time

import pytest
import requests

from btc_analyzer.analysis.ai_forecast import AIService, analyze, validate_report

FACTS = {"asset": "BTC", "anchor": 100.0, "evidence": [{"id": "model"}, {"id": "indicators"}]}
DATA = {
    "summary": "추세가 이어진다는 가정입니다.",
    "low": 90.0,
    "target": 110.0,
    "high": 130.0,
    "reasons": ["model의 경로와 indicators의 모멘텀을 검토했습니다."],
    "risks": ["변동성 확대"],
    "evidence_ids": ["model", "indicators"],
    "invalidation": "지지선 이탈 시 재평가합니다.",
}


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body


def test_openai_responses_protocol_does_not_store_or_send_keys_in_snapshot(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(
            json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(DATA)}]}
                    ],
                }
            ).encode()
        )

    monkeypatch.setattr(requests, "post", post)
    result = analyze(FACTS, "fixture-key", "gpt-4.1-mini")
    assert result.target == 110 and result.model == "gpt-4.1-mini"
    url, request = calls[0]
    assert url == "https://api.openai.com/v1/responses" and request["timeout"] == (5, 20)
    assert request["json"]["store"] is False and request["json"]["text"]["format"]["strict"] is True
    assert "fixture-key" not in json.dumps(request["json"])


@pytest.mark.parametrize(
    "change",
    [
        {"low": 120.0},
        {"target": float("nan")},
        {"high": True},
        {"target": 999999.0},
        {"evidence_ids": ["invented"]},
        {"summary": ""},
        {"reasons": []},
    ],
)
def test_invalid_prices_or_unprovided_evidence_never_become_scenarios(change):
    with pytest.raises(ValueError):
        validate_report({**DATA, **change}, FACTS, "model")


def test_api_errors_are_bounded_and_never_echo_provider_body_or_auth(monkeypatch):
    class Rejected(Response):
        status_code = 401

    monkeypatch.setattr(requests, "post", lambda *a, **k: Rejected(b"fixture-secret from provider"))
    with pytest.raises(ValueError, match="인증") as error:
        analyze(FACTS, "fixture-key", "model")
    assert "fixture-" not in str(error.value)
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(b"x" * 262145))
    with pytest.raises(ValueError, match="크기"):
        analyze(FACTS, "fixture-key", "model")


def test_background_jobs_deduplicate_and_apply_backpressure():
    entered, release = Event(), Event()
    calls = []

    def runner(facts, key, model):
        calls.append(facts)
        entered.set()
        release.wait(3)
        return validate_report(DATA, facts, model)

    service = AIService("fixture-key", "model", runner=runner)
    try:
        first = service.submit(FACTS)
        assert entered.wait(1)
        assert service.snapshot(first).loading
        for _ in range(20):
            assert service.submit(FACTS) == first
        service.submit({**FACTS, "asset": "ETH"})
        with pytest.raises(ValueError, match="진행 중"):
            service.submit({**FACTS, "asset": "SOL"})
        release.set()
        for _ in range(100):
            if service.snapshot(first).report:
                break
            time.sleep(0.005)
        assert service.snapshot(first).report.target == 110
        assert len(calls) <= 2
    finally:
        release.set()
        service.close()
