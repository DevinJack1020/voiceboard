from __future__ import annotations

import streamlit as st

from src.config import database_path
from src.exports import export_csv
from src.repository import VoiceBoardRepository
from src.services.roadmap_service import ROADMAP_STATUSES, RoadmapService
from src.ui import configure_page, render_sidebar_status


configure_page()
render_sidebar_status()
repository = VoiceBoardRepository(database_path())
repository.initialize()
service = RoadmapService(repository)

st.title("产品路线图")
st.caption("管理真实需求卡的负责人、处理状态、目标版本和产品方案。")
if notice := st.session_state.pop("roadmap_notice", None):
    st.success(notice)

all_items = service.list_items(include_archived=True)
if not all_items:
    st.info("还没有需求卡。请从“Top 5 用户痛点”页面创建。", icon="ℹ️")
    st.stop()

include_archived = st.checkbox("显示已归档需求")
active_options = [item for item in all_items if include_archived or not item["archived_at"]]
owners = sorted({item["owner"] for item in active_options if item["owner"]})
versions = sorted(
    {item["target_version"] for item in active_options if item["target_version"]}
)
owner_column, version_column = st.columns(2)
with owner_column:
    owner_filter = st.selectbox("负责人", ["全部", *owners])
with version_column:
    version_filter = st.selectbox("目标版本", ["全部", *versions])

items = service.list_items(
    include_archived=include_archived,
    owner=None if owner_filter == "全部" else owner_filter,
    target_version=None if version_filter == "全部" else version_filter,
)
if not items:
    st.info("当前筛选条件没有需求卡。")
    st.stop()

st.caption(f"当前显示 {len(items)} 张需求卡")
st.download_button(
    "导出当前路线图",
    data=export_csv(
        items,
        (
            "id",
            "title",
            "category",
            "frequency",
            "average_impact",
            "priority_score",
            "owner",
            "status",
            "target_version",
            "solution",
            "created_at",
            "updated_at",
            "archived_at",
        ),
    ),
    file_name="voiceboard_roadmap.csv",
    mime="text/csv",
)
status_columns = st.columns(len(ROADMAP_STATUSES))
for column, status in zip(status_columns, ROADMAP_STATUSES, strict=True):
    with column:
        status_items = [
            item for item in items if item["status"] == status and not item["archived_at"]
        ]
        st.subheader(f"{status} · {len(status_items)}")
        for item in status_items:
            with st.container(border=True):
                st.markdown(f"**{item['title']}**")
                st.caption(
                    f"{item['category']}｜得分 {item['priority_score']:.1f}｜"
                    f"负责人：{item['owner'] or '未分配'}"
                )

st.subheader("需求卡维护")
for item in items:
    archived_label = "（已归档）" if item["archived_at"] else ""
    with st.expander(f"#{item['id']} {item['title']} {archived_label}"):
        if item["archived_at"]:
            st.write(item["solution"])
            if st.button("恢复需求卡", key=f"restore-{item['id']}"):
                service.restore_item(item["id"])
                st.rerun()
            continue
        with st.form(f"roadmap-edit-{item['id']}"):
            title = st.text_input("需求标题", value=item["title"])
            solution = st.text_area("产品方案", value=item["solution"], height=120)
            field_columns = st.columns(3)
            with field_columns[0]:
                owner = st.text_input("负责人", value=item["owner"])
            with field_columns[1]:
                status = st.selectbox(
                    "状态",
                    ROADMAP_STATUSES,
                    index=ROADMAP_STATUSES.index(item["status"]),
                )
            with field_columns[2]:
                target_version = st.text_input("目标版本", value=item["target_version"])
            submitted = st.form_submit_button("保存修改", type="primary")
        if submitted:
            try:
                service.update_item(
                    item["id"], title, solution, owner, status, target_version
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["roadmap_notice"] = "需求卡已更新。"
                st.rerun()
        if st.button("归档需求卡", key=f"archive-{item['id']}"):
            service.archive_item(item["id"])
            st.rerun()
