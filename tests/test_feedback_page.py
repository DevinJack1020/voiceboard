from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_feedback_page_has_an_honest_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(PROJECT_ROOT / "pages" / "2_反馈明细.py"))
    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "反馈明细"
    assert any("还没有反馈" in info.value for info in app.info)

