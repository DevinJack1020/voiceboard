from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.repository import VoiceBoardRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_empty_database_home_explains_the_real_next_step(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "VoiceBoard"
    page_text = "\n".join(element.value for element in app.markdown)
    assert "还没有导入反馈" in page_text
    assert "数据导入" in page_text


def test_home_reads_real_feedback_count_from_sqlite(tmp_path, monkeypatch):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()
    batch_id = repository.create_import_batch("feedback.csv", "rule", 1)
    repository.insert_feedback_batch(
        batch_id,
        [
            {
                "fingerprint": "one",
                "feedback_id": None,
                "feedback_text": "物流太慢",
                "country": "SG",
                "user_type": "新用户",
                "product_category": "电子产品",
                "rating": 2,
                "created_at": "2026-10-20",
                "category": "物流",
                "impact_level": 4,
                "classification_source": "rule",
                "confidence": 0.8,
                "classification_reason": "命中物流",
            }
        ],
    )
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(database))

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    app.run(timeout=10)

    assert not app.exception
    assert app.metric[0].label == "已导入反馈"
    assert app.metric[0].value == "1"
    text = "\n".join(element.value for element in app.markdown)
    assert "还没有导入反馈" not in text

