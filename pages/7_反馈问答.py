from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.agent import answer_question
from src.agent.answer import Answer
from src.config import database_path
from src.repository import VoiceBoardRepository
from src.ui import configure_page, render_sidebar_status


EXAMPLES = (
    "物流类反馈一共有多少条？平均影响程度是多少？",
    "哪个问题分类的反馈最多？",
    "用户具体抱怨物流慢、两周还没到货的反馈有哪些？",
    "物流和支付哪个分类的反馈更多？",
    "巴西市场用户对物流有什么抱怨？",
)

EVIDENCE_COLUMNS = {
    "display_id": "feedback id",
    "feedback_text": "原文",
    "category": "分类",
    "country": "国家",
    "user_type": "用户类型",
    "rating": "评分",
    "impact_level": "影响度",
    "created_at": "时间",
    "score": "BM25",
}


configure_page()
render_sidebar_status()

repository = VoiceBoardRepository(database_path())
repository.initialize()

st.title("反馈问答")
st.caption(
    "对已入库反馈做检索式问答：聚合统计 + 原文引用；证据不足时明确拒答，不编造。"
)

feedback_count = repository.count_feedback()
if feedback_count == 0:
    st.info(
        "还没有反馈，问答 Agent 没有可检索的数据。请先前往“数据导入”上传 CSV。",
        icon="ℹ️",
    )
    st.caption(
        "边界：本页不会在没有数据时展示虚构答案。"
        "检索层只读 SQLite，不调用外部模型（除非显式勾选 DeepSeek 增强）。"
    )
    st.stop()

has_api_key = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())

question_key = "agent_question_text"
if question_key not in st.session_state:
    st.session_state[question_key] = ""
pending = st.session_state.pop("agent_pending_question", None)
if pending:
    st.session_state[question_key] = pending

with st.form("agent-question"):
    typed_question = st.text_input(
        "你的问题",
        key=question_key,
        placeholder="例如：物流类反馈一共有多少条？平均影响程度是多少？",
    )
    with st.columns([1, 1, 2])[1]:
        use_llm = st.checkbox(
            "可选：DeepSeek 增强",
            value=False,
            disabled=not has_api_key,
            help="需要 DEEPSEEK_API_KEY 与网络；输出必须通过严格 JSON 与引用白名单校验，失败自动回退模板。",
        )
    submitted = st.form_submit_button("提问", type="primary")

st.caption("示例问题（点击即提问）：")
example_columns = st.columns(len(EXAMPLES))
for index, example in enumerate(EXAMPLES):
    with example_columns[index]:
        if st.button(example, key=f"agent-example-{index}", use_container_width=True):
            st.session_state["agent_pending_question"] = example
            st.rerun()

active_question = st.session_state.get("agent_active_question", "")
if submitted:
    active_question = (typed_question or "").strip()
    st.session_state["agent_active_question"] = active_question
elif pending:
    active_question = pending
    st.session_state["agent_active_question"] = active_question

if not has_api_key:
    st.caption("未检测到 DEEPSEEK_API_KEY：仅使用确定性模板路径（离线、可复现）。")


def evidence_frame(answer: Answer) -> pd.DataFrame:
    records = []
    for item in answer.evidence:
        records.append(
            {
                "display_id": item.display_id,
                "feedback_text": item.feedback_text,
                "category": item.category,
                "country": item.country,
                "user_type": item.user_type,
                "rating": item.rating,
                "impact_level": item.impact_level,
                "created_at": item.created_at,
                "score": item.score,
            }
        )
    if not records:
        return pd.DataFrame(columns=list(EVIDENCE_COLUMNS))
    frame = pd.DataFrame(records)[list(EVIDENCE_COLUMNS)]
    return frame.rename(columns=EVIDENCE_COLUMNS)


def render_scope(answer: Answer) -> None:
    plan = answer.plan
    with st.expander("检索口径与拒答说明", expanded=False):
        st.markdown(
            f"""
- **识别意图**：`{answer.intent_label}`（detected: `{answer.detected_intent or answer.intent}`）
- **维度过滤**：{plan.filter_summary()}
- **问题词元**：{("、".join(plan.query_tokens)) or "（无）"}
- **命中词**：{("、".join(answer.retrieval.matched_terms) if answer.retrieval and answer.retrieval.matched_terms else "（无）")}
- **候选条数（过滤后全量）**：{answer.retrieval.aggregate.count if answer.retrieval else "—"}
- **参与 BM25 打分的文档数**：{answer.retrieval.corpus_scored if answer.retrieval else "—"}
- **引用条数**：{len(answer.citations)}
- **模式**：`{answer.mode}`；单次耗时约 {answer.latency_ms:.1f} ms
"""
        )
        if plan.notes:
            st.markdown("解析备注：" + "；".join(plan.notes))
        if answer.retrieval and answer.retrieval.notes:
            st.markdown("检索备注：" + "；".join(answer.retrieval.notes))
        st.markdown(
            """
**拒答规则（确定性，非模型自由发挥）**：
1. 问题涉及营收/竞品/预测等库外信息 → 直接拒答；
2. 维度过滤（国家/分类/时间/评分等）后为 0 条 → 拒答，不用其他范围替代；
3. 证据类问题没有任何词面命中，或聚合类问题带库外主题词且无维度可过滤 → 拒答；
4. 对比类问题两侧均为空 → 拒答。
"""
        )


if active_question:
    st.divider()
    answer = answer_question(
        active_question,
        database_path(),
        top_k=5,
        llm=bool(use_llm and has_api_key),
    )
    st.subheader("回答")
    if answer.refused:
        st.warning(answer.text)
    else:
        st.markdown(answer.text)

    metric_columns = st.columns(4)
    metric_columns[0].metric("意图", answer.intent_label)
    metric_columns[1].metric("是否拒答", "是" if answer.refused else "否")
    metric_columns[2].metric("引用条数", len(answer.citations))
    metric_columns[3].metric("单次耗时", f"{answer.latency_ms:.1f} ms")

    st.subheader("证据（只来自检索结果）")
    frame = evidence_frame(answer)
    if frame.empty:
        st.info("没有可展示的证据：本次回答为拒答，未展示任何原文。")
    else:
        st.dataframe(frame, hide_index=True, use_container_width=True)
        st.caption("BM25 为检索打分；对比类问题两侧各取前 3 条，引用按影响度挑选。")

    render_scope(answer)

st.divider()
st.caption(
    "边界声明：本页只对已入库反馈做关键词/中文 bigram 检索 + 确定性模板聚合与引用，"
    "不做语义理解或因果推断，不回答库外问题；引用只来自检索结果。"
    "已知限制：同义改写、跨语言、多轮追问不支持；DeepSeek 增强默认关闭，开启后仍受引用白名单约束。"
)
