import sqlite3

import pytest

from src.repository import VoiceBoardRepository
from src.services.feedback_service import FeedbackFilters, FeedbackService


def record(fingerprint, country, user_type, product_category, category):
    return {
        "fingerprint": fingerprint,
        "feedback_id": None,
        "feedback_text": f"{category}反馈",
        "country": country,
        "user_type": user_type,
        "product_category": product_category,
        "rating": 2,
        "created_at": "2026-10-20",
        "category": category,
        "impact_level": 4,
        "classification_source": "rule",
        "confidence": 0.8,
        "classification_reason": "测试分类",
    }


def seeded_service(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    batch_id = repository.create_import_batch("feedback.csv", "rule", 3)
    repository.insert_feedback_batch(
        batch_id,
        [
            record("sg-new", "SG", "新用户", "电子产品", "物流"),
            record("sg-active", "SG", "活跃用户", "美妆", "支付"),
            record("my-new", "MY", "新用户", "电子产品", "待确认"),
        ],
    )
    return database, FeedbackService(repository)


def test_combined_dimensions_filter_real_database_rows(tmp_path):
    _, service = seeded_service(tmp_path)

    result = service.list_feedback(
        FeedbackFilters(country="SG", user_type="新用户", product_category="电子产品")
    )

    assert result.total == 1
    assert result.records[0]["fingerprint"] == "sg-new"


def test_manual_correction_updates_feedback_and_creates_revision(tmp_path):
    database, service = seeded_service(tmp_path)
    pending = service.list_feedback(FeedbackFilters(category="待确认")).records[0]

    service.correct_feedback(
        pending["id"], category="商品质量", impact_level=5, reason="人工核对原文"
    )

    corrected = service.list_feedback(FeedbackFilters(category="商品质量")).records[0]
    assert corrected["classification_source"] == "manual"
    assert corrected["impact_level"] == 5
    with sqlite3.connect(database) as connection:
        revision = connection.execute(
            "SELECT previous_category, new_category, reason FROM feedback_revisions"
        ).fetchone()
    assert revision == ("待确认", "商品质量", "人工核对原文")


@pytest.mark.parametrize(
    ("category", "impact", "reason"),
    [("广告", 3, "人工"), ("物流", 0, "人工"), ("物流", 3, "")],
)
def test_manual_correction_rejects_invalid_values(tmp_path, category, impact, reason):
    _, service = seeded_service(tmp_path)
    item = service.list_feedback(FeedbackFilters()).records[0]

    with pytest.raises(ValueError):
        service.correct_feedback(item["id"], category, impact, reason)

