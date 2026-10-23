import sqlite3

import pytest

from src.classifiers.deepseek import DeepSeekAPIError
from src.repository import VoiceBoardRepository
from src.services.import_service import ImportService


CSV = """feedback_text,country,user_type,product_category,rating,created_at
包裹一直没有送到,SG,新用户,电子产品,1,2026-10-20
支付一直失败,MY,活跃用户,美妆,2,2026-10-21
""".encode("utf-8")


class FailingClassifier:
    def classify(self, record):
        raise DeepSeekAPIError("DeepSeek 请求超时，请改用离线规则")


def count_batches(database) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]


def test_valid_csv_is_classified_then_committed_as_one_batch(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    service = ImportService(repository)

    prepared = service.prepare(CSV, mode="rule")
    outcome = service.commit("feedback.csv", prepared)

    assert prepared.can_import
    assert {record["category"] for record in prepared.records} == {"物流", "支付"}
    assert outcome.inserted_count == 2
    assert repository.count_feedback() == 2
    assert count_batches(database) == 1


def test_reupload_is_detected_before_commit(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    service = ImportService(repository)
    first = service.prepare(CSV, mode="rule")
    service.commit("feedback.csv", first)

    second = service.prepare(CSV, mode="rule")

    assert not second.can_import
    assert second.duplicate_count == 2
    assert second.records == []


def test_classifier_failure_creates_no_batch_or_feedback(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    service = ImportService(repository)

    with pytest.raises(DeepSeekAPIError):
        service.prepare(CSV, mode="deepseek", classifier=FailingClassifier())

    assert repository.count_feedback() == 0
    assert count_batches(database) == 0

