import json

import pytest
import requests

from src.classifiers.deepseek import (
    DeepSeekAPIError,
    DeepSeekClassifier,
    DeepSeekConfigurationError,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def api_payload(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}


def test_valid_json_response_becomes_a_validated_classification_result():
    session = FakeSession(
        [FakeResponse(api_payload({
            "category": "支付",
            "impact_level": 5,
            "confidence": 0.92,
            "reason": "用户无法完成付款",
        }))]
    )
    classifier = DeepSeekClassifier(api_key="secret-key", session=session)

    result = classifier.classify(
        {"feedback_text": "信用卡一直付款失败", "rating": 1, "impact_level": None}
    )

    assert result.category == "支付"
    assert result.impact_level == 5
    assert result.source == "deepseek"
    request = session.requests[0]
    assert request[0] == "https://api.deepseek.com/chat/completions"
    assert request[1]["json"]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.deepseek.com",
        "https://localhost:8000",
        "https://api.deepseek.com@example.com",
        "https://api.deepseek.com?target=internal",
    ],
)
def test_base_url_rejects_non_https_or_non_deepseek_destinations(base_url):
    with pytest.raises(DeepSeekConfigurationError):
        DeepSeekClassifier(api_key="secret-key", base_url=base_url)


def test_missing_key_is_reported_before_any_network_call():
    with pytest.raises(DeepSeekConfigurationError, match="API Key"):
        DeepSeekClassifier(api_key="")


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        {"category": "广告", "impact_level": 4, "confidence": 0.8, "reason": "x"},
        {"category": "物流", "impact_level": 9, "confidence": 0.8, "reason": "x"},
    ],
)
def test_untrusted_model_output_is_rejected(content):
    response = (
        FakeResponse(api_payload(content))
        if isinstance(content, dict)
        else FakeResponse({"choices": [{"message": {"content": content}}]})
    )
    classifier = DeepSeekClassifier(
        api_key="secret-key", session=FakeSession([response])
    )

    with pytest.raises(DeepSeekAPIError, match="返回格式"):
        classifier.classify({"feedback_text": "测试", "rating": 3})


def test_timeout_is_retried_and_error_never_contains_api_key():
    session = FakeSession(
        [requests.Timeout("secret-key"), requests.Timeout("secret-key")]
    )
    classifier = DeepSeekClassifier(
        api_key="secret-key", session=session, max_retries=1
    )

    with pytest.raises(DeepSeekAPIError) as captured:
        classifier.classify({"feedback_text": "测试", "rating": 3})

    assert len(session.requests) == 2
    assert "secret-key" not in str(captured.value)


def test_model_reason_is_bounded_to_the_documented_length():
    response = FakeResponse(api_payload({
        "category": "物流",
        "impact_level": 4,
        "confidence": 0.8,
        "reason": "长" * 150,
    }))
    classifier = DeepSeekClassifier(
        api_key="secret-key", session=FakeSession([response])
    )

    result = classifier.classify({"feedback_text": "物流很慢", "rating": 2})

    assert len(result.reason) == 100

