"""回答合成层：意图识别 → 确定性模板 / 可选 DeepSeek 增强 → 引用与拒答。

默认路径完全离线、确定性：
- 聚合类（count / attribution）：先按维度过滤做全量 COUNT/AVG，再用 top-k 原文做代表证据；
- 证据类（evidence）：只复述检索命中的原文，不改写、不外推；
- 对比类（comparison）：对两个分类或两个国家分别统计，给出计数/影响对比与各自证据；
- 证据不足：明确输出"当前库内没有足够证据"，不猜测、不编造。

可选路径（默认关闭，页面里需手动勾选且需要 DEEPSEEK_API_KEY）：
- 严格 JSON（answer / cited_ids / refused / reason）；
- cited_ids 必须全部来自本次检索结果，否则整条回退模板；
- 任何解析/网络/校验失败都回退模板，不产出半成品回答。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

import requests

from src.agent.retrieval import (
    AggregateStats,
    Evidence,
    FeedbackRetriever,
    QueryPlan,
    RetrievalResult,
    plan_query,
)


INTENT_COUNT = "count"
INTENT_ATTRIBUTION = "attribution"
INTENT_EVIDENCE = "evidence"
INTENT_COMPARISON = "comparison"
INTENT_REFUSAL = "refusal"

INTENT_LABELS = {
    INTENT_COUNT: "计数",
    INTENT_ATTRIBUTION: "归因/排名",
    INTENT_EVIDENCE: "证据",
    INTENT_COMPARISON: "对比",
    INTENT_REFUSAL: "应拒答",
}

COMPARISON_MARKERS = ("对比", "相比", "比较", "哪个", "哪一个", "谁更", "vs", "还是", "差距")
COUNT_MARKERS = (
    "多少",
    "几条",
    "几件",
    "几个",
    "数量",
    "总量",
    "一共",
    "总共",
    "合计",
    "占比",
    "比例",
    "百分比",
)
ATTRIBUTION_MARKERS = (
    "为什么",
    "原因",
    "痛点",
    "最多",
    "最高",
    "主要问题",
    "归因",
    "排名",
    "top",
    "集中在",
    "哪些问题",
    "主要",
)
EVIDENCE_MARKERS = (
    "原话",
    "原文",
    "例子",
    "举例",
    "证据",
    "具体",
    "抱怨",
    "反馈说",
    "怎么说",
    "哪条",
    "摘录",
    "引用",
    "案例",
    "哪些反馈",
)
GENERIC_AGGREGATE_MARKERS = (
    "分类",
    "占比",
    "分布",
    "全库",
    "整体",
    "总体",
    "全部",
    "所有",
    "排名",
    "痛点",
    "平均",
    "影响程度",
    "总量",
    "总数",
    "反馈有多少",
    "有多少条反馈",
    "哪个分类",
    "各分类",
)
OUT_OF_SCOPE_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "营收",
            "收入",
            "利润",
            "gmv",
            "股价",
            "估值",
            "市值",
            "财务",
            "转化率",
            "留存率",
            "dau",
            "mau",
            "客单价",
            "销售额",
        ),
        "问题涉及经营/财务指标；反馈库只有用户反馈文本、分类与影响度字段，没有这些数据",
    ),
    (
        (
            "竞品",
            "竞争对手",
            "友商",
            "亚马逊",
            "amazon",
            "淘宝",
            "京东",
            "拼多多",
            "shein",
            "temu",
            "shopee",
            "lazada",
            "市场份额",
            "行业第一",
        ),
        "问题涉及外部竞品/行业信息；当前反馈库不包含竞品数据",
    ),
    (
        ("预测", "预计", "会变多", "会变少", "未来", "下季度", "明年", "2027", "2028"),
        "问题要求预测未来；当前库只有历史反馈记录，无法预测",
    ),
)

REFUSAL_LEAD = "当前库内没有足够证据回答这个问题。"
DEFAULT_TOP_K = 5
LLM_TIMEOUT_SECONDS = 20

LLM_SYSTEM_PROMPT = """你是 VoiceBoard 的反馈问答助手。规则：
1. 只能使用 evidence 数组里的反馈原文回答，不得引入外部知识，不得编造数字；
2. cited_ids 必须是 evidence 中真实存在的 id；
3. 如果 evidence 与问题无关，必须 refused=true 并在 reason 说明；
4. 只输出一个 JSON 对象，不要输出 Markdown 或解释。
JSON 结构：{"answer": "中文回答", "cited_ids": ["id"], "refused": false, "reason": ""}"""


@dataclass(frozen=True)
class CategorySide:
    """对比类问题中一侧的统计与证据。"""

    label: str
    dimension: str
    aggregate: AggregateStats
    hits: tuple[Evidence, ...]


@dataclass(frozen=True)
class Answer:
    question: str
    intent: str
    refused: bool
    refusal_reason: str | None
    text: str
    evidence: tuple[Evidence, ...]
    citations: tuple[Evidence, ...]
    plan: QueryPlan
    aggregate: AggregateStats | None
    retrieval: RetrievalResult | None
    sides: tuple[CategorySide, ...] = ()
    mode: str = "template"
    latency_ms: float = 0.0
    notes: tuple[str, ...] = ()
    detected_intent: str | None = None

    @property
    def cited_ids(self) -> tuple[str, ...]:
        return tuple(citation.display_id for citation in self.citations)

    @property
    def intent_label(self) -> str:
        return INTENT_LABELS.get(self.intent, self.intent)


# ---------------------------------------------------------------------------
# 意图识别与拒答判定
# ---------------------------------------------------------------------------


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def detect_intent(question: str, plan: QueryPlan) -> str:
    """五类意图：count / attribution / evidence / comparison / refusal。"""
    text = question.strip()
    if _out_of_scope_reason(text):
        return INTENT_REFUSAL
    comparison_targets = _comparison_targets(plan)
    if comparison_targets is not None and _contains_any(text, COMPARISON_MARKERS):
        return INTENT_COMPARISON
    if _contains_any(text, ATTRIBUTION_MARKERS):
        return INTENT_ATTRIBUTION
    if _contains_any(text, COUNT_MARKERS):
        return INTENT_COUNT
    if _contains_any(text, EVIDENCE_MARKERS):
        return INTENT_EVIDENCE
    if plan.filters or not plan.free_tokens:
        return INTENT_ATTRIBUTION
    return INTENT_EVIDENCE


def _comparison_targets(plan: QueryPlan) -> tuple[str, tuple[str, str]] | None:
    if len(plan.categories) >= 2:
        return "category", (plan.categories[0], plan.categories[1])
    if len(plan.countries) >= 2:
        return "country", (plan.countries[0], plan.countries[1])
    return None


def _out_of_scope_reason(question: str) -> str | None:
    lowered = question.lower()
    for patterns, reason in OUT_OF_SCOPE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return reason
    return None


def _aggregate_question_refusal(question: str, result: RetrievalResult) -> str | None:
    if result.aggregate.count == 0:
        return f"按当前检索口径（{result.plan.filter_summary()}）过滤后为 0 条反馈"
    if result.has_filters or result.free_matched_terms:
        return None
    if _contains_any(question, GENERIC_AGGREGATE_MARKERS):
        return None
    return "问题中的主题词在当前库内没有出现"


def _evidence_refusal(question: str, result: RetrievalResult) -> str | None:
    if result.aggregate.count == 0:
        return f"按当前检索口径（{result.plan.filter_summary()}）过滤后为 0 条反馈"
    if result.has_filters or result.free_matched_terms:
        return None
    return "问题中的主题词在当前库内没有出现"


def _sufficiency_refusal(intent: str, question: str, result: RetrievalResult) -> str | None:
    if intent in (INTENT_COUNT, INTENT_ATTRIBUTION):
        return _aggregate_question_refusal(question, result)
    if intent == INTENT_EVIDENCE:
        return _evidence_refusal(question, result)
    return None


# ---------------------------------------------------------------------------
# 文本格式化
# ---------------------------------------------------------------------------


def _quote(text: str, limit: int = 56) -> str:
    cleaned = " ".join(str(text).split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def _average(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _share(part: int, total: int) -> str:
    return f"{part / total:.1%}" if total else "—"


def _share_text(share: float | None) -> str:
    return "—" if share is None else f"{share:.1%}"


def _distribution_text(values: Sequence[tuple[str, int]]) -> str:
    return "、".join(f"{label} {count} 条" for label, count in values)


def _citation_lines(citations: Sequence[Evidence]) -> str:
    return "；".join(
        f"{citation.display_id}「{_quote(citation.feedback_text)}」" for citation in citations
    )


def _metric_label(metric: str) -> str:
    return {"impact": "平均影响程度", "rating": "平均评分"}.get(metric, "反馈条数")


# ---------------------------------------------------------------------------
# 模板回答
# ---------------------------------------------------------------------------


def _build_refusal(
    question: str,
    plan: QueryPlan,
    reason: str,
    *,
    result: RetrievalResult | None,
    started: float,
) -> Answer:
    corpus = result.corpus_scored if result is not None else 0
    matched = result.free_matched_terms if result is not None else ()
    matched_note = (
        f"命中的主题词：{'、'.join(matched)}"
        if matched
        else "没有命中任何主题词（词面匹配为空）"
    )
    text = "\n\n".join(
        (
            REFUSAL_LEAD,
            f"原因：{reason}。",
            f"已尝试的检索口径：{plan.filter_summary()}；候选 {corpus} 条；{matched_note}。",
            "处理方式：不猜测、不调用外部知识补全、不把无关原文硬当作证据。"
            "如需回答，请先在「数据导入」补充相关反馈，或换一个与已入库反馈相关的问题。",
        )
    )
    return Answer(
        question=question,
        intent=INTENT_REFUSAL,
        refused=True,
        refusal_reason=reason,
        text=text,
        evidence=(),
        citations=(),
        plan=plan,
        aggregate=result.aggregate if result is not None else None,
        retrieval=result,
        mode="template",
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        notes=plan.notes,
    )


def _count_template(question: str, result: RetrievalResult, started: float) -> Answer:
    aggregate = result.aggregate
    scope = result.plan.filter_summary()
    lines = [
        f"在「{scope}」范围内，共有 {aggregate.count} 条反馈。",
        f"平均影响 {_average(aggregate.average_impact)}/5，"
        f"平均评分 {_average(aggregate.average_rating)}/5，"
        f"差评（1–2 星）占比 {_share_text(aggregate.negative_rating_share)}。",
    ]
    if aggregate.by_category:
        lines.append(f"分类分布：{_distribution_text(aggregate.by_category)}。")
    if aggregate.by_country:
        lines.append(f"国家分布：{_distribution_text(aggregate.by_country)}。")
    citations = tuple(result.hits[:3])
    if citations:
        lines.append(f"代表证据：{_citation_lines(citations)}。")
    lines.append(
        "口径：先按维度过滤，再做全量 COUNT/AVG（不是 top-k 外推）；"
        "引用只取自检索命中的原文，未改写。"
    )
    return Answer(
        question=question,
        intent=INTENT_COUNT,
        refused=False,
        refusal_reason=None,
        text="\n\n".join(lines),
        evidence=result.hits,
        citations=citations,
        plan=result.plan,
        aggregate=aggregate,
        retrieval=result,
        mode="template",
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        notes=result.notes,
    )


def _attribution_template(question: str, result: RetrievalResult, started: float) -> Answer:
    aggregate = result.aggregate
    lines: list[str] = []
    selected_category = result.plan.filters.get("category")
    if isinstance(selected_category, str):
        lines.append(
            f"「{selected_category}」是本次检索的分类范围：共 {aggregate.count} 条反馈，"
            f"平均影响 {_average(aggregate.average_impact)}/5。"
        )
    elif aggregate.by_category:
        top_category, top_count = aggregate.by_category[0]
        lines.append(
            f"当前库内反馈最多的分类是「{top_category}」：{top_count} 条"
            f"（占 {_share(top_count, aggregate.count)}）。全库共 {aggregate.count} 条反馈。"
        )
    else:
        lines.append(f"当前检索范围内共有 {aggregate.count} 条反馈。")
    if aggregate.by_category:
        lines.append(f"分类分布：{_distribution_text(aggregate.by_category)}。")
    if aggregate.by_country:
        lines.append(f"国家分布：{_distribution_text(aggregate.by_country)}。")
    citations = tuple(result.hits[:3])
    if citations:
        lines.append(f"代表证据：{_citation_lines(citations)}。")
    lines.append(
        "归因边界：以上只基于反馈条数与影响度的频次/强度聚合，"
        "不推断因果，也不代表外部市场结论；引用取自检索命中的原文。"
    )
    return Answer(
        question=question,
        intent=INTENT_ATTRIBUTION,
        refused=False,
        refusal_reason=None,
        text="\n\n".join(lines),
        evidence=result.hits,
        citations=citations,
        plan=result.plan,
        aggregate=aggregate,
        retrieval=result,
        mode="template",
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        notes=result.notes,
    )


def _evidence_template(question: str, result: RetrievalResult, started: float) -> Answer:
    aggregate = result.aggregate
    citations = tuple(result.hits[:3])
    lines = [
        f"在「{result.plan.filter_summary()}」范围内找到 {aggregate.count} 条反馈，"
        f"下列是检索命中的前 {len(citations)} 条原文："
    ]
    for index, hit in enumerate(citations, start=1):
        lines.append(
            f"{index}. {hit.display_id}「{_quote(hit.feedback_text, 80)}」"
            f"（{hit.metadata_text}）"
        )
    if result.matched_terms:
        lines.append(f"命中词：{'、'.join(result.matched_terms[:12])}。")
    else:
        lines.append("说明：没有词面命中，以下结果按影响度/评分排序，仅代表维度范围，不代表与问题语义相关。")
    lines.append("口径：只复述检索命中的原文，不改写、不总结成因果；引用只来自检索结果。")
    return Answer(
        question=question,
        intent=INTENT_EVIDENCE,
        refused=False,
        refusal_reason=None,
        text="\n\n".join(lines),
        evidence=result.hits,
        citations=citations,
        plan=result.plan,
        aggregate=aggregate,
        retrieval=result,
        mode="template",
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        notes=result.notes,
    )


def _representative_hit(hits: Sequence[Evidence]) -> Evidence | None:
    """代表证据：优先影响度最高，其次评分最低、时间最新。"""
    if not hits:
        return None
    return max(
        hits,
        key=lambda item: (item.impact_level, -item.rating, item.created_at, -item.row_id),
    )


def _comparison_template(
    question: str,
    plan: QueryPlan,
    sides: tuple[CategorySide, ...],
    metric: str,
    started: float,
) -> Answer:
    all_hits = tuple(hit for side in sides for hit in side.hits)
    citations = tuple(
        representative
        for side in sides
        if (representative := _representative_hit(side.hits)) is not None
    )
    lines = [
        f"对比（检索口径：{plan.filter_summary()}；比较维度：{_metric_label(metric)}）："
    ]
    for side in sides:
        aggregate = side.aggregate
        representative = _representative_hit(side.hits)
        evidence_text = (
            f"代表证据 {representative.display_id}「{_quote(representative.feedback_text)}」"
            if representative
            else "没有可用证据"
        )
        lines.append(
            f"- {side.label}：{aggregate.count} 条，"
            f"平均影响 {_average(aggregate.average_impact)}/5，"
            f"平均评分 {_average(aggregate.average_rating)}/5；{evidence_text}。"
        )
    # 结论
    if metric == "impact":
        values = [(side.label, side.aggregate.average_impact or 0.0) for side in sides]
        label = "平均影响程度"
    elif metric == "rating":
        values = [(side.label, side.aggregate.average_rating or 0.0) for side in sides]
        label = "平均评分"
    else:
        values = [(side.label, float(side.aggregate.count)) for side in sides]
        label = "反馈条数"
    first_label, first_value = values[0]
    second_label, second_value = values[1]
    if abs(first_value - second_value) < 1e-9:
        lines.append(f"结论：按{label}，{first_label}与{second_label}接近（持平）。")
    elif first_value > second_value:
        lines.append(
            f"结论：按{label}，{first_label}更高（{first_value:g} vs {second_value:g}）。"
        )
    else:
        lines.append(
            f"结论：按{label}，{second_label}更高（{second_value:g} vs {first_value:g}）。"
        )
    lines.append("口径：两侧分别按维度过滤后做全量统计，各自引用本侧检索命中的原文。")
    return Answer(
        question=question,
        intent=INTENT_COMPARISON,
        refused=False,
        refusal_reason=None,
        text="\n\n".join(lines),
        evidence=all_hits,
        citations=citations,
        plan=plan,
        aggregate=None,
        retrieval=None,
        sides=sides,
        mode="template",
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        notes=plan.notes,
    )


def _comparison_metric(question: str) -> str:
    text = question.lower()
    if any(word in text for word in ("影响", "严重", "优先级")):
        return "impact"
    if any(word in text for word in ("评分", "星级", "星")):
        return "rating"
    return "count"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def answer_question(
    question: str,
    database: Path | str | FeedbackRetriever,
    *,
    top_k: int = DEFAULT_TOP_K,
    llm: bool = False,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Answer:
    """回答一个关于已入库反馈的问题。

    - 默认纯模板、离线、确定性；
    - llm=True 且存在 DEEPSEEK_API_KEY 时尝试增强，任何失败/校验不通过都回退模板。
    """
    started = time.perf_counter()
    retriever = (
        database
        if isinstance(database, FeedbackRetriever)
        else FeedbackRetriever(database)
    )
    cleaned_question = " ".join(str(question or "").split())
    if not cleaned_question:
        plan = plan_query("")
        return _build_refusal(
            question,
            plan,
            "问题为空，未进行检索",
            result=None,
            started=started,
        )
    plan = plan_query(cleaned_question)
    intent = detect_intent(cleaned_question, plan)
    detected_intent = intent

    def finalize(candidate: Answer) -> Answer:
        return replace(candidate, detected_intent=detected_intent)

    if intent == INTENT_REFUSAL:
        reason = _out_of_scope_reason(cleaned_question) or "问题超出反馈库覆盖范围"
        # 仍然跑一次检索，把"我看到了什么"如实展示给用户
        try:
            result = retriever.search(cleaned_question, top_k=top_k)
        except Exception:  # pragma: no cover - 仅防御 page 空库等异常
            result = None
        return finalize(
            _build_refusal(cleaned_question, plan, reason, result=result, started=started)
        )

    if intent == INTENT_COMPARISON:
        targets = _comparison_targets(plan)
        if targets is not None:
            dimension, labels = targets
            sides_aggregates: list[CategorySide] = []
            for label in labels:
                side_result = retriever.search(
                    cleaned_question,
                    top_k=3,
                    extra_filters={dimension: label},
                )
                sides_aggregates.append(
                    CategorySide(
                        label=label,
                        dimension=dimension,
                        aggregate=side_result.aggregate,
                        hits=side_result.hits,
                    )
                )
            if all(side.aggregate.count == 0 for side in sides_aggregates):
                return finalize(
                    _build_refusal(
                        cleaned_question,
                        plan,
                        "两侧筛选后均为 0 条反馈，无法对比",
                        result=retriever.search(cleaned_question, top_k=top_k),
                        started=started,
                    )
                )
            answer = _comparison_template(
                cleaned_question,
                plan,
                tuple(sides_aggregates),
                _comparison_metric(cleaned_question),
                started,
            )
            if llm:
                enhanced = _try_llm_enhance(
                    answer,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                )
                if enhanced is not None:
                    return finalize(enhanced)
            return finalize(answer)

    result = retriever.search(cleaned_question, top_k=top_k)
    refusal_reason = _sufficiency_refusal(intent, cleaned_question, result)
    if refusal_reason:
        return finalize(
            _build_refusal(
                cleaned_question,
                result.plan,
                refusal_reason,
                result=result,
                started=started,
            )
        )
    if intent == INTENT_COUNT:
        answer = _count_template(cleaned_question, result, started)
    elif intent == INTENT_ATTRIBUTION:
        answer = _attribution_template(cleaned_question, result, started)
    else:
        answer = _evidence_template(cleaned_question, result, started)
    if llm:
        enhanced = _try_llm_enhance(
            answer,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        if enhanced is not None:
            return finalize(enhanced)
    return finalize(answer)


# ---------------------------------------------------------------------------
# 可选 DeepSeek 增强（严格 JSON + 引用校验 + 失败回退）
# ---------------------------------------------------------------------------


def build_llm_messages(question: str, evidence: Sequence[Evidence]) -> list[dict[str, str]]:
    payload = {
        "question": question,
        "evidence": [
            {
                "id": item.display_id,
                "text": item.feedback_text,
                "category": item.category,
                "country": item.country,
                "rating": item.rating,
                "impact": item.impact_level,
            }
            for item in evidence
        ],
    }
    return [
        {"role": "system", "content": LLM_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def validate_llm_payload(raw: str, allowed_ids: Sequence[str]) -> dict | None:
    """校验 LLM 输出；不合格返回 None（调用方回退模板）。"""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    refused = bool(payload.get("refused", False))
    reason = payload.get("reason")
    cited_ids = payload.get("cited_ids", [])
    if not isinstance(cited_ids, list) or not all(isinstance(item, str) for item in cited_ids):
        return None
    allowed = set(allowed_ids)
    invalid = [item for item in cited_ids if item not in allowed]
    if invalid:
        return None
    if not refused and not cited_ids:
        return None
    return {
        "answer": answer.strip(),
        "cited_ids": list(dict.fromkeys(cited_ids)),
        "refused": refused,
        "reason": reason if isinstance(reason, str) else "",
    }


def _call_deepseek(
    messages: Sequence[Mapping[str, str]],
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": list(messages),
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        },
        timeout=LLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"])


def _try_llm_enhance(
    answer: Answer,
    *,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
) -> Answer | None:
    resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not resolved_key:
        return None
    resolved_model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    resolved_base = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    evidence = answer.evidence
    if not evidence:
        return None
    allowed_ids = [item.display_id for item in evidence]
    started = time.perf_counter()
    try:
        raw = _call_deepseek(
            build_llm_messages(answer.question, evidence),
            api_key=resolved_key,
            model=resolved_model,
            base_url=resolved_base,
        )
        payload = validate_llm_payload(raw, allowed_ids)
    except Exception:  # pragma: no cover - 网络/鉴权失败时静默回退
        return None
    if payload is None or payload["refused"]:
        return None
    by_id = {item.display_id: item for item in evidence}
    citations = tuple(by_id[item] for item in payload["cited_ids"])
    if not citations:
        return None
    text = (
        f"{payload['answer']}\n\n"
        f"引用（只来自本次检索结果）：{_citation_lines(citations)}。\n\n"
        "口径：模型回答已通过引用白名单校验；统计数字来自检索层的确定性聚合。"
    )
    return replace(
        answer,
        text=text,
        citations=citations,
        mode="template+deepseek",
        notes=tuple(answer.notes) + ("DeepSeek 增强已开启，输出通过严格 JSON 与引用校验",),
        latency_ms=round(
            answer.latency_ms + (time.perf_counter() - started) * 1000,
            2,
        ),
    )
