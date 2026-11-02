from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import database_path
from src.repository import VoiceBoardRepository
from src.services.evaluation_service import (
    BADCASE_LAYERS,
    EvaluationResult,
    EvaluationService,
    badcase_layer_counts,
    filter_badcases,
    format_cny,
    format_decimal,
    format_int,
    format_ms,
    format_percent,
    format_tokens,
)
from src.ui import configure_page, render_sidebar_status


SOURCE_LABELS = {"rule": "规则", "deepseek": "DeepSeek", "manual": "人工修订"}

configure_page()
render_sidebar_status()
repository = VoiceBoardRepository(database_path())
repository.initialize()
service = EvaluationService(repository)

st.title("评测与 Badcase")
st.caption("用离线小样本评测与运行时人工修订率，检查分类是否可信、错误集中在哪里。")
st.warning(
    "离线小样本评测，不代表线上效果。评测集由项目自建、单标注者标注，"
    "指标只用于版本回归和错误归因，不构成线上 SLA 或收益承诺。",
    icon="⚠️",
)


def render_result_metrics(result: EvaluationResult) -> None:
    """指标卡：准确率、召回、待确认率、修订率估计、延迟、token 与成本。"""
    st.subheader("核心指标")
    top_columns = st.columns(4)
    top_columns[0].metric("评测样本", format_int(result.dataset_size))
    top_columns[1].metric(
        "业务类准确率", format_percent(result.metric_number("accuracy_business"))
    )
    top_columns[2].metric(
        "端到端准确率", format_percent(result.metric_number("accuracy_e2e"))
    )
    top_columns[3].metric(
        "Macro Recall（业务类）",
        format_percent(result.metric_number("macro_recall_business")),
    )

    key_recall = result.key_class_recall
    recall_columns = st.columns(4)
    for column, category in zip(recall_columns[:3], ("物流", "支付", "商品质量")):
        column.metric(f"关键类召回 · {category}", format_percent(key_recall.get(category)))
    recall_columns[3].metric(
        "待确认率", format_percent(result.metric_number("uncertain_rate"))
    )

    cost_columns = st.columns(5)
    cost_columns[0].metric(
        "人工修订率估计",
        format_percent(result.metric_number("human_revision_rate_estimate")),
    )
    cost_columns[1].metric("p50 延迟", format_ms(result.latency_number("p50_ms")))
    cost_columns[2].metric("p95 延迟", format_ms(result.latency_number("p95_ms")))
    cost_columns[3].metric("总 token", format_tokens(result.cost_number("total_tokens")))
    cost_columns[4].metric("估算成本", format_cny(result.cost_number("estimated_cny")))

    st.caption(
        f"影响度 MAE：{format_decimal(result.metrics.get('impact_mae'), 3)}｜"
        f"影响度完全一致率：{format_percent(result.metrics.get('impact_exact_rate'))}｜"
        f"错误数：{format_int(result.latency.get('n_errors'))}｜"
        f"输入 token：{format_tokens(result.cost_number('prompt_tokens'))}｜"
        f"输出 token：{format_tokens(result.cost_number('completion_tokens'))}｜"
        f"平均延迟：{format_ms(result.latency_number('mean_ms'))}"
    )
    st.caption(
        f"待确认诊断：业务类→待确认 "
        f"{format_percent(result.metric_number('business_to_uncertain_rate'))}｜"
        f"待确认→业务类 {format_percent(result.metric_number('uncertain_to_business_rate'))}。"
        "人工修订率估计 = (预测为待确认的样本数 + 业务类误判数) / n，"
        "是假设全部输出经人工复核后的离线代理指标，不是线上真实修订率；"
        "线上口径见下方 SQLite 实测统计。"
    )
    if result.pricing_note:
        st.caption(f"成本口径：{result.pricing_note}")


results = service.load_results()
if not results:
    st.subheader("暂无评测结果")
    st.warning(
        "没有找到 evals/results/deepseek_v1.json 或 evals/results/rule_v1.json，"
        "页面不展示任何占位数字。请先运行评测脚本生成结果。",
        icon="ℹ️",
    )
    st.markdown("需要 `evals/feedback_eval_v1.csv`，并在仓库根目录用项目虚拟环境运行：")
    st.code(
        ".\\\\.venv\\\\Scripts\\\\python.exe scripts/run_eval.py --mode rule "
        "--out evals/results/rule_v1.json\n"
        ".\\\\.venv\\\\Scripts\\\\python.exe scripts/run_eval.py --mode deepseek "
        "--out evals/results/deepseek_v1.json --predictions-out "
        "evals/results/predictions_deepseek_v1.csv --badcases-out "
        "evals/results/badcases_v1.csv",
        language="powershell",
    )
    st.caption("完整参数（数据集路径、输出路径、limit、模型、密钥环境变量）用 `--help` 查看。")
else:
    selected_label = results[0].label
    if len(results) > 1:
        selected_label = st.radio(
            "结果文件", [result.label for result in results], horizontal=True
        )
    result = next(item for item in results if item.label == selected_label)

    st.markdown(
        f"**结果文件**：`evals/results/{result.source_path.name}`　|　"
        f"**模式**：{result.mode or '未记录'}　|　**模型**：{result.model or '未记录'}　|　"
        f"**prompt 版本**：{result.prompt_version or '未记录'}"
    )
    st.markdown(
        f"**评测集**：`{result.dataset or '未记录'}`（{format_int(result.dataset_size)} 条）　|　"
        f"**运行时间**：{result.timestamp or '未记录'}　|　**run_id**：`{result.run_id or '未记录'}`"
    )
    st.caption(
        "评测集来源、抽样方法与许可说明见 evals/README.md；标注规约（六类定义、多意图/反讽/"
        "待确认/影响度判定）见 evals/labeling-guideline.md。标注方法：单人标注 golden 分类，"
        "未做标注一致性检验，这是本评测的已知局限。"
    )
    if result.failures:
        st.error(
            f"本次运行记录了 {len(result.failures)} 条失败，结果可能不完整，"
            "请查看结果 JSON 的 failures 字段。"
        )

    render_result_metrics(result)

    per_class = result.per_class
    if per_class:
        st.subheader("每类 Precision / Recall / F1")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "类别": category,
                        "Precision": format_percent(values["precision"]),
                        "Recall": format_percent(values["recall"]),
                        "F1": format_percent(values["f1"]),
                        "Support": format_int(values["support"]),
                    }
                    for category, values in per_class.items()
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        st.caption("Precision / Recall / F1 以百分比展示，Support 为该类 golden 样本数。")
    else:
        st.info("结果 JSON 里没有 per_class 明细，无法展示每类指标。", icon="ℹ️")

    confusion = result.confusion_matrix
    if confusion:
        st.subheader("混淆矩阵（行 = golden，列 = 预测）")
        predicted_labels: list[str] = []
        for row in confusion.values():
            for predicted in row:
                if predicted not in predicted_labels:
                    predicted_labels.append(predicted)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "golden \\ predicted": golden,
                        **{
                            predicted: row.get(predicted, 0)
                            for predicted in predicted_labels
                        },
                    }
                    for golden, row in confusion.items()
                ]
            ).set_index("golden \\ predicted"),
            use_container_width=True,
        )
        st.caption("数字为样本数；对角线为分类正确，非对角线是主要错误方向。")
    else:
        st.info("结果 JSON 里没有混淆矩阵，无法展示错误方向。", icon="ℹ️")

st.divider()

st.subheader("Badcase 归因")
cases = service.load_badcases()
if not cases:
    st.info(
        "还没有 Badcase 记录（evals/results/badcases_v1.csv 缺失或为空）。"
        "生成评测结果后会在这里按归因层级展示原文、golden、预测、归因与改进建议。",
        icon="ℹ️",
    )
else:
    counts = badcase_layer_counts(cases)
    count_text = "｜".join(f"{layer} {counts[layer]}" for layer in BADCASE_LAYERS)
    st.caption(
        "层级定义：数据 = golden 歧义或缺上下文；提示词 = 类别边界、多意图、反讽未被 prompt 覆盖；"
        "规则 = 关键词误命中、并列、待确认阈值；交互 = 待确认展示、人工复核路径、影响度展示。"
    )
    selected_layer = st.selectbox("按归因层级筛选", ["全部", *BADCASE_LAYERS])
    filtered = filter_badcases(
        cases, None if selected_layer == "全部" else selected_layer
    )
    st.caption(
        f"共 {len(filtered)} 条 Badcase（全部 {len(cases)} 条；{count_text}）。"
    )
    if filtered:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "样本ID": case.eval_id,
                        "原文": case.feedback_text,
                        "golden 分类": case.golden_category,
                        "预测分类": case.predicted_category,
                        "置信度": format_decimal(case.confidence, 2),
                        "归因层级": case.layer_label,
                        "归因说明": case.reason,
                        "改进建议": case.proposed_fix,
                    }
                    for case in filtered
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info(f"当前层级“{selected_layer}”没有 Badcase。")

st.divider()

st.subheader("运行时人工修订统计（来自 SQLite）")
stats = service.revision_statistics()
if stats.total_feedback == 0:
    st.info(
        "SQLite 里还没有导入反馈。先到“数据导入”上传真实 CSV，这里会显示真实的"
        "待确认占比与人工修订率，不使用占位数字。",
        icon="ℹ️",
    )
else:
    stat_columns = st.columns(5)
    stat_columns[0].metric("已分类反馈", format_int(stats.classified_count))
    stat_columns[1].metric("待确认反馈", format_int(stats.uncertain_count))
    stat_columns[2].metric("待确认占比", format_percent(stats.uncertain_rate))
    stat_columns[3].metric("有修订记录的反馈", format_int(stats.revised_feedback_count))
    stat_columns[4].metric("人工修订率", format_percent(stats.human_revision_rate))
    st.caption(
        f"口径：已分类反馈 = classification_source ∈ {{rule, deepseek, manual}}；"
        "待确认是分类结果（category = 待确认），仍计入已分类分母。"
        f"人工修订率 = 有修订记录的 distinct feedback 数 / 已分类反馈数；"
        f"当前共 {format_int(stats.revision_count)} 条修订记录，同一反馈多次修订按 1 条计。"
    )

    source_column, product_column = st.columns(2)
    with source_column:
        st.markdown("**按分类来源的修订率**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "分类来源": SOURCE_LABELS.get(row.source, row.source or "未记录"),
                        "反馈数": format_int(row.total),
                        "有修订": format_int(row.revised),
                        "修订率": format_percent(row.revision_rate),
                    }
                    for row in stats.by_source
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    with product_column:
        st.markdown("**待确认占比（按商品品类）**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "商品品类": row.product_category or "未记录",
                        "反馈数": format_int(row.total),
                        "待确认": format_int(row.uncertain),
                        "待确认占比": format_percent(row.uncertain_rate),
                    }
                    for row in stats.uncertain_by_product_category
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    with st.expander("分类结果分布（含待确认占比）"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "分类": row.category or "未记录",
                        "反馈数": format_int(row.count),
                        "占比": format_percent(row.share),
                    }
                    for row in stats.category_shares
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

st.divider()
st.caption(
    "边界声明：离线小样本评测，不代表线上效果；评测集自建、单标注者且无标注一致性检验。"
    "人工修订率来自本地 SQLite 审计记录（feedback_revisions），衡量“自动分类结果被人工改写的比例”，"
    "不是线上真实用户修订率。"
)
