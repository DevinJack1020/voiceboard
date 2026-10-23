from src.analytics import calculate_priority, top_pain_points


def item(category, impact, country="SG"):
    return {
        "category": category,
        "impact_level": impact,
        "country": country,
        "feedback_text": f"{category}问题",
    }


def test_priority_is_frequency_times_unrounded_average_impact():
    records = [
        item("物流", 4),
        item("物流", 5),
        item("支付", 3),
        item("支付", 3),
        item("支付", 3),
    ]

    result = calculate_priority(records)

    logistics = next(row for row in result if row["category"] == "物流")
    payment = next(row for row in result if row["category"] == "支付")
    assert logistics == {
        "category": "物流",
        "frequency": 2,
        "average_impact": 4.5,
        "priority_score": 9.0,
    }
    assert payment["priority_score"] == 9.0
    assert result[0]["category"] == "物流"


def test_pending_feedback_is_excluded_and_empty_input_is_supported():
    assert calculate_priority([]) == []
    assert calculate_priority([item("待确认", 5)]) == []


def test_top_pain_points_returns_at_most_five_ranked_categories():
    categories = ["物流", "支付", "商品质量", "搜索推荐", "客服", "退换货"]
    records = [item(category, 5) for category in categories]

    top = top_pain_points(records)

    assert len(top) == 5
    assert [row["rank"] for row in top] == [1, 2, 3, 4, 5]

