from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from src.config import database_path
from src.repository import VoiceBoardRepository
from src.services.feedback_service import FeedbackFilters, FeedbackService
from src.services.insight_service import InsightService
from src.ui import configure_page, render_sidebar_status


configure_page()
render_sidebar_status()
repository = VoiceBoardRepository(database_path())
repository.initialize()
feedback_service = FeedbackService(repository)
insight_service = InsightService(repository)

st.title("Top 5 用户痛点")
st.caption("排名来自当前筛选数据；每个痛点都可追溯原始反馈并转为持久化需求卡。")

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
filter_data = asdict(filters)
records, total = repository.query_feedback(filter_data, limit=20_000)
insights = insight_service.build_insights(records, filter_data)

if total == 0:
    st.info("当前筛选条件没有可分析的反馈。")
    st.stop()
if not insights:
    st.info("筛选结果全部处于“待确认”，请先在反馈明细页完成分类。")
    st.stop()

for insight in insights:
    st.subheader(f"#{insight.rank}　{insight.category}")
    metric_columns = st.columns(3)
    metric_columns[0].metric("出现频次", insight.frequency)
    metric_columns[1].metric("平均影响", f"{insight.average_impact:.1f}")
    metric_columns[2].metric("优先级得分", f"{insight.priority_score:.1f}")
    with st.expander("查看构成该结论的反馈证据"):
        for evidence in insight.evidence:
            st.markdown(f"- {evidence}")
    with st.form(f"roadmap-{insight.category}"):
        solution = st.text_area("产品方案", value=insight.solution, height=100)
        owner_column, version_column = st.columns(2)
        with owner_column:
            owner = st.text_input("负责人", placeholder="例如：物流产品组")
        with version_column:
            target_version = st.text_input("目标版本", placeholder="例如：V1.1")
        submitted = st.form_submit_button("转为需求卡", type="primary")
    if submitted:
        try:
            result = insight_service.create_roadmap_item(
                insight, solution, owner, target_version
            )
        except ValueError as error:
            st.error(str(error))
        else:
            if result.created:
                st.success(f"需求卡 #{result.item_id} 已写入产品路线图。")
            else:
                st.info(f"相同决策快照已存在于需求卡 #{result.item_id}。")
    st.divider()
