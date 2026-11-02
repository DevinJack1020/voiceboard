import json

import pytest
import requests

from src.classifiers.deepseek import (
    PROMPT_VERSION,
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


# ---------------------------------------------------------------------------
# classify_with_meta：评测引擎需要 token 用量与延迟埋点
# ---------------------------------------------------------------------------


def api_payload_with_usage(content: dict, usage: dict | None = None) -> dict:
    payload = api_payload(content)
    if usage is not None:
        payload["usage"] = usage
    return payload


VALID_CONTENT = {
    "category": "支付",
    "impact_level": 5,
    "confidence": 0.92,
    "reason": "用户无法完成付款",
}
VALID_USAGE = {
    "prompt_tokens": 321,
    "completion_tokens": 87,
    "total_tokens": 408,
}


def test_classify_with_meta_returns_usage_and_latency():
    session = FakeSession([FakeResponse(api_payload_with_usage(VALID_CONTENT, VALID_USAGE))])
    classifier = DeepSeekClassifier(api_key="secret-key", session=session)

    result, meta = classifier.classify_with_meta(
        {"feedback_text": "信用卡一直付款失败", "rating": 1, "impact_level": None}
    )

    assert result.category == "支付"
    assert result.source == "deepseek"
    assert set(meta) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
    }
    assert meta["prompt_tokens"] == 321
    assert meta["completion_tokens"] == 87
    assert meta["total_tokens"] == 408
    assert isinstance(meta["latency_ms"], float)
    assert meta["latency_ms"] >= 0.0


def test_classify_with_meta_defaults_missing_or_invalid_usage_to_zero():
    classifier = DeepSeekClassifier(
        api_key="secret-key", session=FakeSession([FakeResponse(api_payload(VALID_CONTENT))])
    )
    _result, meta = classifier.classify_with_meta({"feedback_text": "付款失败", "rating": 1})

    assert meta["prompt_tokens"] == 0
    assert meta["completion_tokens"] == 0
    assert meta["total_tokens"] == 0

    broken_usage = {"prompt_tokens": "321", "completion_tokens": -1, "total_tokens": None}
    classifier = DeepSeekClassifier(
        api_key="secret-key",
        session=FakeSession([FakeResponse(api_payload_with_usage(VALID_CONTENT, broken_usage))]),
    )
    _result, meta = classifier.classify_with_meta({"feedback_text": "付款失败", "rating": 1})

    assert meta["prompt_tokens"] == 0
    assert meta["completion_tokens"] == 0
    assert meta["total_tokens"] == 0


def test_classify_with_meta_total_tokens_falls_back_to_sum():
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    classifier = DeepSeekClassifier(
        api_key="secret-key",
        session=FakeSession([FakeResponse(api_payload_with_usage(VALID_CONTENT, usage))]),
    )

    _result, meta = classifier.classify_with_meta({"feedback_text": "付款失败", "rating": 1})

    assert meta["total_tokens"] == 15


def test_classify_with_meta_invalid_response_still_raises_and_has_no_meta():
    response = FakeResponse(api_payload_with_usage({"category": "广告"}, VALID_USAGE))
    classifier = DeepSeekClassifier(api_key="secret-key", session=FakeSession([response]))

    with pytest.raises(DeepSeekAPIError, match="返回格式"):
        classifier.classify_with_meta({"feedback_text": "测试", "rating": 3})


def test_classify_with_meta_keeps_explicit_impact_override_semantics():
    classifier = DeepSeekClassifier(
        api_key="secret-key",
        session=FakeSession([FakeResponse(api_payload_with_usage(VALID_CONTENT, VALID_USAGE))]),
    )

    result, meta = classifier.classify_with_meta(
        {"feedback_text": "付款失败", "rating": 1, "impact_level": 2}
    )

    assert result.impact_level == 2
    assert meta["prompt_tokens"] == 321


def test_classify_with_meta_retries_timeouts_and_reports_wall_clock_latency():
    session = FakeSession(
        [
            requests.Timeout("secret-key"),
            FakeResponse(api_payload_with_usage(VALID_CONTENT, VALID_USAGE)),
        ]
    )
    classifier = DeepSeekClassifier(api_key="secret-key", session=session, max_retries=1)

    result, meta = classifier.classify_with_meta({"feedback_text": "付款失败", "rating": 1})

    assert result.category == "支付"
    assert len(session.requests) == 2
    assert meta["latency_ms"] >= 0.0
    assert "secret-key" not in str(meta)


def test_classify_remains_compatible_with_classify_with_meta():
    def build_classifier():
        return DeepSeekClassifier(
            api_key="secret-key",
            session=FakeSession([FakeResponse(api_payload_with_usage(VALID_CONTENT, VALID_USAGE))]),
        )

    legacy = build_classifier().classify({"feedback_text": "付款失败", "rating": 1})
    decorated, meta = build_classifier().classify_with_meta({"feedback_text": "付款失败", "rating": 1})

    assert legacy == decorated
    assert meta["prompt_tokens"] == 321


def test_prompt_version_is_a_stable_non_empty_constant():
    assert isinstance(PROMPT_VERSION, str)
    assert PROMPT_VERSION.strip()
    assert PROMPT_VERSION == "deepseek-classify-v2"


def test_payload_uses_current_model_thinking_disabled_and_json_example():
    session = FakeSession([FakeResponse(api_payload_with_usage(VALID_CONTENT, VALID_USAGE))])
    classifier = DeepSeekClassifier(api_key="secret-key", session=session)

    classifier.classify_with_meta({"feedback_text": "付款失败", "rating": 1})

    payload = session.requests[0][1]["json"]
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["temperature"] == 0
    system_prompt = payload["messages"][0]["content"]
    assert "阿拉伯数字整数" in system_prompt
    assert '"impact_level": 4' in system_prompt


@pytest.mark.parametrize(
    ("raw_impact", "expected"),
    [
        ("四", 4),
        ("一", 1),
        ("五", 5),
        ("4", 4),
        (4.0, 4),
    ],
)
def test_impact_level_is_safely_normalized_before_strict_validation(raw_impact, expected):
    content = {
        "category": "物流",
        "impact_level": raw_impact,
        "confidence": 0.8,
        "reason": "配送延误",
    }
    classifier = DeepSeekClassifier(
        api_key="secret-key",
        session=FakeSession([FakeResponse(api_payload_with_usage(content, VALID_USAGE))]),
    )

    result = classifier.classify({"feedback_text": "快递很慢", "rating": 2})

    assert result.impact_level == expected
    assert isinstance(result.impact_level, int)


@pytest.mark.parametrize(
    "raw_impact",
    ["六", "四星", "abc", 0, 6, -1, True, None],
)
def test_out_of_range_or_unmappable_impact_is_still_rejected(raw_impact):
    content = {
        "category": "物流",
        "impact_level": raw_impact,
        "confidence": 0.8,
        "reason": "配送延误",
    }
    classifier = DeepSeekClassifier(
        api_key="secret-key",
        session=FakeSession([FakeResponse(api_payload_with_usage(content, VALID_USAGE))]),
    )

    with pytest.raises(DeepSeekAPIError, match="返回格式"):
        classifier.classify({"feedback_text": "快递很慢", "rating": 2})



