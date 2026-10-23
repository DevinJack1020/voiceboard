from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.classifiers.deepseek import (
    DeepSeekAPIError,
    DeepSeekClassifier,
    DeepSeekConfigurationError,
)
from src.config import database_path
from src.importer import CsvValidationError, build_template_csv
from src.repository import VoiceBoardRepository
from src.services.import_service import ImportService, PreparedImport
from src.ui import configure_page, render_sidebar_status


configure_page()
render_sidebar_status()

repository = VoiceBoardRepository(database_path())
repository.initialize()
service = ImportService(repository)

st.title("数据导入")
st.markdown("上传真实反馈，先校验和分类预览，确认后才写入 SQLite。")

template_column, status_column = st.columns([1, 2])
with template_column:
    st.download_button(
        "下载空白 CSV 模板",
        data=build_template_csv(),
        file_name="voiceboard_feedback_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
with status_column:
    st.caption(f"当前数据库已有 {repository.count_feedback():,} 条反馈")

mode_label = st.radio(
    "分类方式",
    options=("离线规则", "DeepSeek"),
    horizontal=True,
    help="离线规则无需网络；DeepSeek 会把反馈正文发送到官方 API。",
)
api_key = ""
if mode_label == "DeepSeek":
    st.caption("为避免意外 API 费用，DeepSeek 模式单批最多处理 100 条反馈。")
    api_key = st.text_input(
        "DeepSeek API Key",
        type="password",
        value="",
        help="仅用于本次会话请求，不会写入数据库或日志。留空时读取环境变量。",
    )
    if os.getenv("DEEPSEEK_API_KEY"):
        st.caption("已检测到环境变量中的 API Key；输入框可继续留空。")

uploaded = st.file_uploader(
    "选择 UTF-8 CSV 文件",
    type=("csv",),
    help="单个文件最多 10 MB、20,000 行。",
)

if uploaded is None:
    st.info("请先下载模板并上传真实反馈。系统不会自动载入样例数据。", icon="ℹ️")
else:
    st.caption(f"已选择：{uploaded.name}（{uploaded.size / 1024:.1f} KB）")
    if st.button("校验并生成分类预览", type="primary"):
        # A failed new attempt must never leave an older file's preview
        # available for confirmation under the newly selected filename.
        st.session_state.pop("prepared_import", None)
        st.session_state.pop("prepared_filename", None)
        try:
            mode = "deepseek" if mode_label == "DeepSeek" else "rule"
            classifier = None
            if mode == "deepseek":
                classifier = DeepSeekClassifier(
                    api_key=api_key or os.getenv("DEEPSEEK_API_KEY", ""),
                    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                )
            st.session_state["prepared_import"] = service.prepare(
                uploaded.getvalue(), mode=mode, classifier=classifier
            )
            st.session_state["prepared_filename"] = uploaded.name
        except (CsvValidationError, DeepSeekConfigurationError, DeepSeekAPIError) as error:
            st.error(str(error))

prepared: PreparedImport | None = st.session_state.get("prepared_import")
if prepared is not None:
    st.divider()
    st.subheader("导入预览")
    if prepared.duplicate_count:
        st.warning(f"发现 {prepared.duplicate_count} 条重复反馈，已从预览中排除。")
    if prepared.errors:
        st.error("CSV 存在错误，修正后重新上传。")
        st.dataframe(
            pd.DataFrame(
                [
                    {"行号": error.row_number or "文件", "问题": error.message}
                    for error in prepared.errors
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    elif not prepared.records:
        st.info("没有新的可导入反馈。")
    else:
        preview_columns = [
            "feedback_text",
            "country",
            "user_type",
            "product_category",
            "rating",
            "created_at",
            "category",
            "impact_level",
            "classification_source",
            "confidence",
        ]
        st.dataframe(
            pd.DataFrame(prepared.records)[preview_columns],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(f"确认后将写入 {len(prepared.records):,} 条反馈。")
        if st.button("确认写入 SQLite", type="primary"):
            outcome = service.commit(
                st.session_state["prepared_filename"], prepared
            )
            st.success(f"已真实写入 {outcome.inserted_count:,} 条反馈。")
            del st.session_state["prepared_import"]
            del st.session_state["prepared_filename"]
