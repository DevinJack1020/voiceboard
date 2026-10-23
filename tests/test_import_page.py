from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_import_page_offers_template_and_waits_for_real_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(PROJECT_ROOT / "pages" / "1_数据导入.py"))
    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "数据导入"
    text = "\n".join(element.value for element in app.markdown)
    assert "上传真实反馈" in text
    assert len(app.get("download_button")) == 1

