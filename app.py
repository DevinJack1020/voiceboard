from __future__ import annotations

import streamlit as st

from src.ui import configure_page, render_sidebar_status


configure_page()
render_sidebar_status()

st.title("VoiceBoard")
st.caption("跨境电商用户反馈与产品路线图平台")

st.markdown("### 还没有导入反馈")
st.markdown(
    "前往左侧 **数据导入** 页面下载标准 CSV 模板并上传真实反馈。"
    "在没有数据前，本页不会展示虚构的指标或图表。"
)

st.info(
    "导入后，你可以依次完成：反馈分类 → 优先级计算 → Top 5 痛点 → 需求路线图。",
    icon="ℹ️",
)

