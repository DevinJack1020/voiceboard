from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_priority_page_has_an_honest_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(PROJECT_ROOT / "pages" / "3_优先级看板.py"))
    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "优先级看板"
    assert any("没有可分析的反馈" in info.value for info in app.info)

