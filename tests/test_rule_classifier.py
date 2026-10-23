import pytest

from src.classifiers.rule import RuleClassifier


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        ("包裹配送三天了还没到", "物流"),
        ("信用卡付款一直失败", "支付"),
        ("收到的耳机破损而且有杂音", "商品质量"),
        ("搜索结果完全不相关，推荐也很差", "搜索推荐"),
        ("客服两天没有回复", "客服"),
        ("申请退款后一直没有处理", "退换货"),
        ("Parcel delivery is delayed", "物流"),
    ],
)
def test_typical_feedback_is_classified_into_six_business_categories(
    text, expected_category
):
    result = RuleClassifier().classify({"feedback_text": text, "rating": 2})

    assert result.category == expected_category
    assert result.source == "rule"
    assert result.reason


def test_unmatched_or_tied_feedback_requires_manual_confirmation():
    classifier = RuleClassifier()

    unmatched = classifier.classify({"feedback_text": "整体感觉一般", "rating": 3})
    tied = classifier.classify(
        {"feedback_text": "物流客服", "rating": 3}
    )

    assert unmatched.category == "待确认"
    assert tied.category == "待确认"
    assert tied.confidence < 0.6


def test_explicit_impact_is_preserved_and_urgent_terms_raise_estimate():
    classifier = RuleClassifier()

    explicit = classifier.classify(
        {"feedback_text": "物流稍慢", "rating": 4, "impact_level": 5}
    )
    urgent = classifier.classify(
        {"feedback_text": "付款失败并且重复扣款", "rating": 3, "impact_level": None}
    )

    assert explicit.impact_level == 5
    assert urgent.impact_level == 4

