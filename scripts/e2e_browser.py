from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "e2e_feedback.csv"
SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "e2e"
DATABASE = Path(os.environ["VOICEBOARD_DB_PATH"])
BASE_URL = os.getenv("VOICEBOARD_E2E_URL", "http://localhost:8501")
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")


def wait_for_streamlit(page) -> None:
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    page.locator("[data-testid='stAppViewContainer']").wait_for(timeout=20_000)


def navigate(page, label: str) -> None:
    sidebar = page.locator("[data-testid='stSidebar']")
    sidebar.get_by_text(label, exact=True).click()
    wait_for_streamlit(page)


def select_streamlit_option(page, label: str, option: str) -> None:
    control = page.get_by_label(label, exact=True)
    control.click()
    # Streamlit 1.66 renders this as a React Aria virtual combobox. The
    # expanded options are announced through a live region instead of being
    # exposed as ordinary DOM option nodes, so keyboard events must target the
    # input itself; the sibling open button closes again when headless. The
    # first keypress activates the rerendered input and the second opens it.
    control.press("ArrowDown")
    page.wait_for_timeout(300)
    control.press("ArrowDown")
    page.get_by_role("option", name=option, exact=True).click()
    assert control.input_value() == option


def database_counts() -> tuple[int, int, int, str]:
    with sqlite3.connect(DATABASE) as connection:
        feedback = connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        revisions = connection.execute(
            "SELECT COUNT(*) FROM feedback_revisions"
        ).fetchone()[0]
        roadmap = connection.execute("SELECT COUNT(*) FROM roadmap_items").fetchone()[0]
        status = connection.execute(
            "SELECT status FROM roadmap_items ORDER BY id LIMIT 1"
        ).fetchone()[0]
    return feedback, revisions, roadmap, status


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(EDGE),
            headless=True,
            args=["--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        wait_for_streamlit(page)
        page.get_by_text("还没有导入反馈", exact=True).wait_for()
        page.screenshot(path=SCREENSHOT_DIR / "01-empty-home.png", full_page=True)

        navigate(page, "数据导入")
        page.locator("input[type='file']").set_input_files(str(FIXTURE))
        page.get_by_role("button", name="校验并生成分类预览").click()
        page.get_by_text("导入预览", exact=True).wait_for(timeout=20_000)
        page.get_by_text("确认后将写入 11 条反馈。", exact=True).wait_for()
        page.screenshot(path=SCREENSHOT_DIR / "02-import-preview.png", full_page=True)
        page.get_by_role("button", name="确认写入 SQLite").click()
        page.get_by_text("已真实写入 11 条反馈。", exact=True).wait_for(timeout=20_000)

        navigate(page, "反馈明细")
        page.get_by_text("筛选结果：11 条", exact=False).wait_for()
        page.get_by_label("修订原因").fill("浏览器验收：人工核对为客服问题")
        page.get_by_role("button", name="保存人工修订").click()
        page.get_by_text("修订已保存", exact=False).wait_for(timeout=20_000)

        navigate(page, "优先级看板")
        page.get_by_text("优先级排名", exact=True).wait_for()
        page.wait_for_timeout(1_500)
        page.screenshot(path=SCREENSHOT_DIR / "03-priority-dashboard.png", full_page=True)

        navigate(page, "Top5痛点")
        page.get_by_text("#1", exact=False).first.wait_for()
        page.get_by_label("负责人").first.fill("履约产品组")
        page.get_by_label("目标版本").first.fill("V1.1")
        page.get_by_role("button", name="转为需求卡").first.click()
        page.get_by_text("已写入产品路线图", exact=False).wait_for(timeout=20_000)

        navigate(page, "产品路线图")
        page.get_by_text("待评估 · 1", exact=True).wait_for()
        page.get_by_text("#1", exact=False).last.click()
        select_streamlit_option(page, "状态", "开发中")
        page.get_by_role("button", name="保存修改").click()
        page.get_by_text("需求卡已更新", exact=False).wait_for(timeout=20_000)
        page.screenshot(path=SCREENSHOT_DIR / "04-roadmap.png", full_page=True)

        browser.close()

    feedback, revisions, roadmap, status = database_counts()
    assert (feedback, revisions, roadmap, status) == (11, 1, 1, "开发中")
    assert not console_errors, f"browser console errors: {console_errors}"
    print("browser_flow=passed")
    print(f"feedback={feedback} revisions={revisions} roadmap={roadmap} status={status}")
    print(f"screenshots={SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
