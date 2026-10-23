from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from src.analytics import calculate_priority
from src.config import database_path
from src.exports import export_csv
from src.repository import VoiceBoardRepository
from src.services.feedback_service import FeedbackFilters, FeedbackService
from src.ui import configure_page, render_sidebar_status


configure_page()
render_sidebar_status()
repository = VoiceBoardRepository(database_path())
repository.initialize()
feedback_service = FeedbackService(repository)

st.title("优先级看板")
st.caption("公式透明：优先级得分 = 当前筛选范围内出现频次 × 平均影响程度。")

if repository.count_feedback() == 0:
    st.info("没有可分析的反馈。请先前往“数据导入”上传 CSV。", icon="ℹ️")
    st.stop()


def filter_select(label: str, column: str) -> str | None:
    selected = st.selectbox(label, ["全部", *feedback_service.filter_options(column)])
    return None if selected == "全部" else selected


country_column, user_column, product_column = st.columns(3)
with country_column:
    country = filter_select("国家/市场", "country")
with user_column:
    user_type = filter_select("用户类型", "user_type")
with product_column:
    product_category = filter_select("商品品类", "product_category")

filters = FeedbackFilters(
    country=country,
    user_type=user_type,
    product_category=product_category,
)
records, total = repository.query_feedback(asdict(filters), limit=20_000)
priorities = calculate_priority(records)

if total == 0:
    st.info("当前筛选条件没有可分析的反馈。")
    st.stop()

high_impact = sum(int(record["impact_level"]) >= 4 for record in records)
pending = sum(record["category"] == "待确认" for record in records)
markets = len({record["country"] for record in records})
metric_columns = st.columns(4)
metric_columns[0].metric("筛选反馈", f"{total:,}")
metric_columns[1].metric("高影响反馈", f"{high_impact:,}")
metric_columns[2].metric("待确认", f"{pending:,}")
metric_columns[3].metric("覆盖市场", f"{markets:,}")

if not priorities:
    st.info("筛选结果全部处于“待确认”，请先在反馈明细页完成分类。")
    st.stop()

priority_frame = pd.DataFrame(priorities)
chart_column, table_column = st.columns([1.25, 1])
with chart_column:
    st.subheader("频次 × 影响矩阵")
    st.scatter_chart(
        priority_frame,
        x="frequency",
        y="average_impact",
        size="priority_score",
        color="category",
        use_container_width=True,
    )
with table_column:
    st.subheader("优先级排名")
    st.dataframe(
        priority_frame.rename(
            columns={
                "category": "问题分类",
                "frequency": "出现频次",
                "average_impact": "平均影响",
                "priority_score": "优先级得分",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.download_button(
        "导出优先级结果",
        data=export_csv(
            priorities,
            ("category", "frequency", "average_impact", "priority_score"),
        ),
        file_name="voiceboard_priority.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.subheader("原始证据")
for priority in priorities:
    category_records = [
        record for record in records if record["category"] == priority["category"]
    ]
    with st.expander(
        f"{priority['category']}｜{priority['frequency']} 条｜得分 {priority['priority_score']}"
    ):
        st.dataframe(
            pd.DataFrame(category_records)[
                ["feedback_text", "country", "user_type", "product_category", "impact_level"]
            ],
            hide_index=True,
            use_container_width=True,
        )
