from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_top5_page_has_an_honest_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(PROJECT_ROOT / "pages" / "4_Top5痛点.py"))
    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Top 5 用户痛点"
    assert any("没有可分析的反馈" in info.value for info in app.info)

