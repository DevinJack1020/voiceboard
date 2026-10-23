from __future__ import annotations

import math
from dataclasses import asdict

import pandas as pd
import streamlit as st

from src.classifiers.base import BUSINESS_CATEGORIES
from src.config import database_path
from src.exports import export_csv
from src.repository import VoiceBoardRepository
from src.services.feedback_service import FeedbackFilters, FeedbackService
from src.ui import configure_page, render_sidebar_status


configure_page()
render_sidebar_status()
repository = VoiceBoardRepository(database_path())
repository.initialize()
service = FeedbackService(repository)

st.title("反馈明细")
st.caption("查看真实入库反馈、分类来源和影响程度，并对自动结果进行人工修订。")
if notice := st.session_state.pop("feedback_notice", None):
    st.success(notice)

if repository.count_feedback() == 0:
    st.info("还没有反馈。请先前往“数据导入”上传 CSV。", icon="ℹ️")
    st.stop()


def filter_select(label: str, column: str) -> str | None:
    selected = st.selectbox(label, ["全部", *service.filter_options(column)])
    return None if selected == "全部" else selected


country_column, user_column, product_column, category_column = st.columns(4)
with country_column:
    country = filter_select("国家/市场", "country")
with user_column:
    user_type = filter_select("用户类型", "user_type")
with product_column:
    product_category = filter_select("商品品类", "product_category")
with category_column:
    category = filter_select("问题分类", "category")

filters = FeedbackFilters(
    country=country,
    user_type=user_type,
    product_category=product_category,
    category=category,
)
first_page = service.list_feedback(filters)
page_count = max(1, math.ceil(first_page.total / first_page.page_size))
page_number = int(
    st.number_input("页码", min_value=1, max_value=page_count, value=1, step=1)
)
result = first_page if page_number == 1 else service.list_feedback(filters, page_number)

st.caption(f"筛选结果：{result.total:,} 条；第 {result.page}/{page_count} 页")
if not result.records:
    st.info("当前筛选条件没有结果，请调整筛选项。")
    st.stop()

display_columns = [
    "id",
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
    "classification_reason",
]
st.dataframe(
    pd.DataFrame(result.records)[display_columns],
    hide_index=True,
    use_container_width=True,
)
all_filtered_records, _ = repository.query_feedback(asdict(filters), limit=20_000)
st.download_button(
    "导出当前筛选反馈",
    data=export_csv(all_filtered_records, display_columns),
    file_name="voiceboard_filtered_feedback.csv",
    mime="text/csv",
)

st.subheader("人工修订")
record_by_id = {record["id"]: record for record in result.records}
with st.form("feedback-correction"):
    selected_id = st.selectbox("反馈 ID", list(record_by_id))
    selected_record = record_by_id[selected_id]
    selected_category = st.selectbox(
        "修正分类",
        BUSINESS_CATEGORIES,
        index=(
            BUSINESS_CATEGORIES.index(selected_record["category"])
            if selected_record["category"] in BUSINESS_CATEGORIES
            else 0
        ),
    )
    selected_impact = st.slider(
        "影响程度", 1, 5, int(selected_record["impact_level"])
    )
    correction_reason = st.text_input("修订原因", placeholder="例如：人工核对原文后确认")
    submitted = st.form_submit_button("保存人工修订", type="primary")

if submitted:
    try:
        service.correct_feedback(
            selected_id, selected_category, selected_impact, correction_reason
        )
    except ValueError as error:
        st.error(str(error))
    else:
        st.session_state["feedback_notice"] = "修订已保存，并写入审计记录。"
        st.rerun()
