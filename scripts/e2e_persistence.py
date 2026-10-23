from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DATABASE = Path(os.environ["VOICEBOARD_DB_PATH"])
BASE_URL = os.getenv("VOICEBOARD_E2E_URL", "http://localhost:8501")
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")


def main() -> None:
    with sqlite3.connect(DATABASE) as connection:
        stored = connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        status = connection.execute(
            "SELECT status FROM roadmap_items ORDER BY id LIMIT 1"
        ).fetchone()[0]
    assert (stored, status) == (11, "开发中")

    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(EDGE), headless=True, args=["--disable-gpu"]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.locator("[data-testid='stAppViewContainer']").wait_for(timeout=20_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        page.get_by_text("已导入反馈").wait_for()
        page.get_by_text("11", exact=True).first.wait_for()
        sidebar = page.locator("[data-testid='stSidebar']")
        sidebar.get_by_text("产品路线图", exact=True).click()
        page.get_by_text("开发中 · 1", exact=True).wait_for(timeout=20_000)
        browser.close()

    assert not console_errors, f"browser console errors: {console_errors}"
    print("restart_persistence=passed")
    print(f"feedback={stored} roadmap_status={status}")


if __name__ == "__main__":
    main()
