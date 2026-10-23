from __future__ import annotations

import streamlit as st


def configure_page() -> None:
    st.set_page_config(
        page_title="VoiceBoard",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root { --vb-accent: #0f766e; }
        .stApp { background: #f8fafc; }
        [data-testid="stSidebar"] { background: #f1f5f9; }
        h1, h2, h3 { color: #0f172a; letter-spacing: -0.02em; }
        div[data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #e2e8f0;
            border-radius: 8px; padding: 0.75rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_status() -> None:
    with st.sidebar:
        st.caption("本地产品决策工作台")
        st.success("SQLite 将保存你的真实数据", icon="✅")

