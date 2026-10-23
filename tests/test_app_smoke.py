from pathlib import Path

from streamlit.testing.v1 import AppTest


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

