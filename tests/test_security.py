import sqlite3

from src.repository import VoiceBoardRepository


def test_filter_value_is_data_not_executable_sql(tmp_path):
    database = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(database)
    repository.initialize()

    records, total = repository.query_feedback({"country": "' OR 1=1 --"})

    assert records == []
    assert total == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'feedback'"
        ).fetchone()[0] == 1

