import sqlite3

import pytest

from src.repository import VoiceBoardRepository


def feedback_record(fingerprint: str, text: str = "包裹一直没有送到") -> dict:
    return {
        "fingerprint": fingerprint,
        "feedback_id": None,
        "feedback_text": text,
        "country": "SG",
        "user_type": "新用户",
        "product_category": "电子产品",
        "rating": 1,
        "created_at": "2026-10-20",
        "category": "物流",
        "impact_level": 5,
        "classification_source": "rule",
        "confidence": 0.95,
        "classification_reason": "命中：包裹、送到",
    }


def test_schema_initialization_is_idempotent_and_creates_core_tables(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)

    repository.initialize()
    repository.initialize()

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"import_batches", "feedback", "feedback_revisions", "roadmap_items"} <= tables


def test_feedback_survives_reconnection_and_duplicate_fingerprint_is_ignored(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    batch_id = repository.create_import_batch("feedback.csv", "rule", 2)

    inserted = repository.insert_feedback_batch(
        batch_id,
        [feedback_record("same"), feedback_record("same")],
    )

    reopened = VoiceBoardRepository(database)
    assert inserted == 1
    assert reopened.count_feedback() == 1


def test_failed_batch_rolls_back_all_feedback_rows(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    batch_id = repository.create_import_batch("feedback.csv", "rule", 2)
    invalid = feedback_record("invalid")
    invalid["impact_level"] = 7

    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_feedback_batch(
            batch_id,
            [feedback_record("valid"), invalid],
        )

    assert repository.count_feedback() == 0

