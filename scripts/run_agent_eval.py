"""反馈问答 / 归因 Agent 的离线评测脚本（15 题）。

跑什么：
- 用确定性评测语料（30 条中文跨境电商反馈，内置于本脚本）建一个临时 SQLite 库；
- 逐题调用 src.agent.answer.answer_question（默认纯模板、离线、无 LLM）；
- 计算 retrieval hit@5、引用有效率、拒答正确率、误拒答率、意图匹配率、关键词命中率、p50/p95 延迟；
- 输出机器可读 JSON（默认 evals/results/agent_v1.json）。

为什么用内置语料：
- 仓库 data/voiceboard.db 当前为空，evals/ 的真实标注集是分类评测集（且不覆盖问答所需的完整反馈记录）；
- 内置语料保证任何人都能在任意机器上复现同一组数字，用来做"机制回归"，不是效果证明。
- 真实数据上待测：见 docs/agent-scope.md 的"下一步"。若提供 --real-corpus，
  脚本会把真实标注集当检索语料跑 5 条冒烟问题（只报告"是否有证据/引用是否有效/是否误拒答"，不算 hit@5）。

怎么跑：
    python scripts/run_agent_eval.py
    python scripts/run_agent_eval.py --out evals/results/agent_v1.json --db .tmp/agent_eval.db
    python scripts/run_agent_eval.py --real-corpus evals/feedback_eval_v1.csv

注意：命令里写中文时建议文件用 UTF-8；脚本自身只把回答原文写进 JSON，终端只打印 ASCII 摘要。
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.answer import (  # noqa: E402
    INTENT_ATTRIBUTION,
    INTENT_COMPARISON,
    INTENT_COUNT,
    INTENT_EVIDENCE,
    INTENT_REFUSAL,
    Answer,
    answer_question,
)
from src.classifiers.rule import RuleClassifier  # noqa: E402
from src.repository import VoiceBoardRepository  # noqa: E402


DEFAULT_QUESTIONS = PROJECT_ROOT / "evals" / "agent_questions_v1.csv"
DEFAULT_OUT = PROJECT_ROOT / "evals" / "results" / "agent_v1.json"
DEFAULT_TOP_K = 5

EXPECTED_TYPE_TO_INTENTS: dict[str, tuple[str, ...]] = {
    "aggregate": (INTENT_COUNT, INTENT_ATTRIBUTION),
    "evidence": (INTENT_EVIDENCE,),
    "comparison": (INTENT_COMPARISON,),
    "refusal": (INTENT_REFUSAL,),
}

# 确定性评测语料：30 条跨境电商用户反馈（中文），覆盖 6 个业务分类、5 个国家、2026-09/10 两个月。
# 语料与问题/期望证据是一起设计的，属于"受控回归集"：比真实数据简单，数字不代表线上效果。
EVAL_CORPUS: tuple[dict[str, object], ...] = (
    # 物流 8 条
    {"fid": "F01", "text": "包裹显示已签收但我没收到，联系快递也没用", "category": "物流", "country": "SG", "rating": 1, "impact": 5, "product": "电子产品", "created": "2026-10-31"},
    {"fid": "F02", "text": "物流太慢，下单两周了还没到，比预计晚了一周", "category": "物流", "country": "MY", "rating": 2, "impact": 4, "product": "服饰", "created": "2026-09-12"},
    {"fid": "F03", "text": "快递把盒子压扁了，里面的面霜漏出来了", "category": "物流", "country": "TH", "rating": 1, "impact": 5, "product": "美妆", "created": "2026-10-25"},
    {"fid": "F04", "text": "清关卡了十天，物流信息一直不更新", "category": "物流", "country": "ID", "rating": 2, "impact": 4, "product": "家居", "created": "2026-09-05"},
    {"fid": "F05", "text": "配送员没有打电话就把包裹放在门口，结果丢了", "category": "物流", "country": "SG", "rating": 2, "impact": 4, "product": "母婴", "created": "2026-10-12"},
    {"fid": "F06", "text": "发到美国的包裹被退回仓库，没有任何通知", "category": "物流", "country": "US", "rating": 1, "impact": 5, "product": "电子产品", "created": "2026-10-24"},
    {"fid": "F07", "text": "物流比预计慢两天，东西倒是没坏", "category": "物流", "country": "MY", "rating": 3, "impact": 3, "product": "食品", "created": "2026-09-18"},
    {"fid": "F08", "text": "同一订单分三个包裹发，最后只收到两个，第三个一直查不到", "category": "物流", "country": "SG", "rating": 2, "impact": 4, "product": "服饰", "created": "2026-09-28"},
    # 支付 6 条
    {"fid": "F09", "text": "用信用卡付款失败三次，最后换了另一个支付方式才成功", "category": "支付", "country": "SG", "rating": 1, "impact": 5, "product": "电子产品", "created": "2026-10-30"},
    {"fid": "F10", "text": "重复扣款了两笔，客服说会退但一周了没到账", "category": "支付", "country": "MY", "rating": 1, "impact": 5, "product": "服饰", "created": "2026-09-08"},
    {"fid": "F11", "text": "PayPal 付款一直转圈，页面卡住后订单没生成", "category": "支付", "country": "TH", "rating": 2, "impact": 4, "product": "美妆", "created": "2026-10-15"},
    {"fid": "F12", "text": "结算时汇率和我看到的不一样，多付了几块钱", "category": "支付", "country": "ID", "rating": 2, "impact": 4, "product": "家居", "created": "2026-09-22"},
    {"fid": "F13", "text": "支付成功但订单显示未支付，钱已经扣了", "category": "支付", "country": "US", "rating": 1, "impact": 5, "product": "电子产品", "created": "2026-10-05"},
    {"fid": "F14", "text": "本地钱包选项经常灰掉，只能用银行卡", "category": "支付", "country": "SG", "rating": 3, "impact": 3, "product": "母婴", "created": "2026-10-18"},
    # 商品质量 5 条
    {"fid": "F15", "text": "衣服面料和图片差很多，起球严重，穿了两次就变形", "category": "商品质量", "country": "MY", "rating": 2, "impact": 4, "product": "服饰", "created": "2026-09-25"},
    {"fid": "F16", "text": "收到的面霜有异味，怀疑是假货", "category": "商品质量", "country": "TH", "rating": 1, "impact": 5, "product": "美妆", "created": "2026-10-20"},
    {"fid": "F17", "text": "耳机左耳没声音，明显是质量问题", "category": "商品质量", "country": "SG", "rating": 1, "impact": 5, "product": "电子产品", "created": "2026-10-29"},
    {"fid": "F18", "text": "椅子腿是裂的，做工粗糙，螺丝也对不上", "category": "商品质量", "country": "ID", "rating": 2, "impact": 4, "product": "家居", "created": "2026-09-30"},
    {"fid": "F19", "text": "零食包装胀气，保质期只剩一个月", "category": "商品质量", "country": "US", "rating": 2, "impact": 4, "product": "食品", "created": "2026-10-08"},
    # 客服 4 条
    {"fid": "F20", "text": "客服一直机器人回复，转人工排了四十分钟也没人接", "category": "客服", "country": "SG", "rating": 1, "impact": 5, "product": "电子产品", "created": "2026-10-27"},
    {"fid": "F21", "text": "问客服退货地址，回复很慢而且说法前后不一致", "category": "客服", "country": "MY", "rating": 2, "impact": 4, "product": "服饰", "created": "2026-09-10"},
    {"fid": "F22", "text": "客服态度不耐烦，问题没解决就关掉对话", "category": "客服", "country": "TH", "rating": 2, "impact": 4, "product": "美妆", "created": "2026-10-02"},
    {"fid": "F23", "text": "促销时说好的赠品，联系客服三天才回", "category": "客服", "country": "ID", "rating": 3, "impact": 3, "product": "家居", "created": "2026-09-16"},
    # 退换货 4 条
    {"fid": "F24", "text": "退货申请被拒绝了两次，理由每次都不一样", "category": "退换货", "country": "SG", "rating": 1, "impact": 5, "product": "服饰", "created": "2026-10-26"},
    {"fid": "F25", "text": "退款拖了半个月还没到账，售后一直让等", "category": "退换货", "country": "US", "rating": 2, "impact": 4, "product": "电子产品", "created": "2026-09-14"},
    {"fid": "F26", "text": "换货寄回去之后仓库说没收到，流程卡住", "category": "退换货", "country": "MY", "rating": 2, "impact": 4, "product": "美妆", "created": "2026-10-22"},
    {"fid": "F27", "text": "退货要自己承担运费，比商品还贵", "category": "退换货", "country": "TH", "rating": 2, "impact": 4, "product": "家居", "created": "2026-09-02"},
    # 搜索推荐 3 条
    {"fid": "F28", "text": "搜索“耳机”出来的都是手机壳，搜不到想要的东西", "category": "搜索推荐", "country": "ID", "rating": 2, "impact": 3, "product": "电子产品", "created": "2026-09-26"},
    {"fid": "F29", "text": "推荐的都是我买过的同类，几乎没有新东西", "category": "搜索推荐", "country": "SG", "rating": 3, "impact": 3, "product": "服饰", "created": "2026-10-10"},
    {"fid": "F30", "text": "筛选按价格排序后结果乱七八糟，排序没生效", "category": "搜索推荐", "country": "US", "rating": 2, "impact": 3, "product": "食品", "created": "2026-09-24"},
)

REAL_SMOKE_QUESTIONS: tuple[str, ...] = (
    "物流类反馈有多少条？",
    "退款相关的反馈有哪些？",
    "客服相关的反馈有多少条？",
    "delivery delay or lost parcel feedback",
    "印度用户对物流的反馈有哪些？",
    "巴西市场用户对物流的抱怨是什么？",
)


# ---------------------------------------------------------------------------
# 语料与问题
# ---------------------------------------------------------------------------


def _feedback_record(item: dict[str, object]) -> dict[str, object]:
    return {
        "fingerprint": f"agent-eval-{item['fid']}",
        "feedback_id": str(item["fid"]),
        "feedback_text": item["text"],
        "country": item["country"],
        "user_type": "新用户",
        "product_category": item["product"],
        "rating": item["rating"],
        "created_at": item["created"],
        "category": item["category"],
        "impact_level": item["impact"],
        "classification_source": "rule",
        "confidence": 0.9,
        "classification_reason": "评测语料固定标签",
    }


def seed_fixture_database(database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()
    repository = VoiceBoardRepository(database)
    repository.initialize()
    records = [_feedback_record(item) for item in EVAL_CORPUS]
    repository.import_feedback(
        "agent_eval_fixture_v1.csv",
        "rule",
        len(records),
        records,
    )


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(";") if part.strip())


def _shorten(text: str, limit: int) -> str:
    cleaned = " ".join(str(text).split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def load_questions(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    questions: list[dict[str, object]] = []
    for row in rows:
        question_id = (row.get("question_id") or "").strip()
        question = (row.get("question") or "").strip()
        expected_type = (row.get("expected_type") or "").strip()
        if not question_id or not question:
            raise ValueError(f"问题行缺少 question_id/question：{row}")
        if expected_type not in EXPECTED_TYPE_TO_INTENTS:
            raise ValueError(f"未知 expected_type={expected_type}（{question_id}）")
        questions.append(
            {
                "question_id": question_id,
                "question": question,
                "expected_type": expected_type,
                "expected_feedback_ids": _split(row.get("expected_feedback_ids")),
                "expected_keywords": _split(row.get("expected_keywords")),
                "note": (row.get("note") or "").strip(),
            }
        )
    return questions


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _latency_summary(latencies: list[float]) -> dict[str, float]:
    if not latencies:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "p50": round(statistics.median(latencies), 2),
        "p95": round(_percentile(latencies, 0.95), 2),
        "mean": round(statistics.fmean(latencies), 2),
        "max": round(max(latencies), 2),
    }


def evaluate_question(
    question_row: dict[str, object],
    database: Path,
    *,
    top_k: int,
) -> dict[str, object]:
    question = str(question_row["question"])
    expected_type = str(question_row["expected_type"])
    answer: Answer = answer_question(question, database, top_k=top_k)
    retrieved_ids = [item.display_id for item in answer.evidence]
    expected_ids = list(question_row["expected_feedback_ids"])  # type: ignore[arg-type]
    expected_keywords = list(question_row["expected_keywords"])  # type: ignore[arg-type]
    # hit@5 只在"答案依赖排序检索"的题上计算（聚合类 + 证据类）。
    # 对比类由维度过滤 + 全量 SQL 聚合出答案，候选由过滤条件保证，
    # 对排序做 hit 判定没有信息量，因此单独用 comparison_coverage 检查两侧覆盖与引用。
    hit_eligible = bool(expected_ids) and expected_type in ("aggregate", "evidence")
    retrieval_hit = (
        any(item in retrieved_ids for item in expected_ids) if hit_eligible else None
    )
    citation_records = []
    for citation in answer.citations:
        valid = (
            citation.display_id in retrieved_ids
            and bool(str(citation.feedback_text).strip())
        )
        citation_records.append({"id": citation.display_id, "valid": valid})
    allowed_intents = EXPECTED_TYPE_TO_INTENTS[expected_type]
    side_records = [
        {
            "label": side.label,
            "dimension": side.dimension,
            "count": side.aggregate.count,
            "hits": [hit.display_id for hit in side.hits],
        }
        for side in answer.sides
    ]
    comparison_coverage = None
    if expected_type == "comparison":
        comparison_coverage = (
            len(side_records) == 2
            and all(side["count"] > 0 and side["hits"] for side in side_records)
            and len(answer.citations) >= 2
        )
    return {
        "question_id": question_row["question_id"],
        "question": question,
        "expected_type": expected_type,
        "expected_feedback_ids": expected_ids,
        "expected_keywords": expected_keywords,
        "intent": answer.intent,
        "detected_intent": answer.detected_intent or answer.intent,
        "intent_match": answer.intent in allowed_intents,
        "refused": answer.refused,
        "refusal_reason": answer.refusal_reason,
        "filter_summary": answer.plan.filter_summary(),
        "retrieved_ids": retrieved_ids,
        "hit_eligible": hit_eligible,
        "retrieval_hit": retrieval_hit,
        "citations": citation_records,
        "citation_total": len(citation_records),
        "citation_valid": sum(1 for item in citation_records if item["valid"]),
        "keyword_hit": (
            all(keyword in answer.text for keyword in expected_keywords)
            if expected_keywords
            else None
        ),
        "latency_ms": answer.latency_ms,
        "matched_terms": list(answer.retrieval.matched_terms) if answer.retrieval else [],
        "sides": side_records,
        "comparison_coverage": comparison_coverage,
        "mode": answer.mode,
        "answer_excerpt": _shorten(answer.text, 140),
    }


def _public_row(row: dict[str, object]) -> dict[str, object]:
    """落盘用的精简逐题记录（完整回答可由回答层复跑得到）。"""
    excerpt = str(row["answer_excerpt"])
    return {
        "question_id": row["question_id"],
        "expected_type": row["expected_type"],
        "intent": row["intent"],
        "refused": row["refused"],
        "retrieval_hit": row["retrieval_hit"],
        "citation": f"{row['citation_valid']}/{row['citation_total']}",
        "keyword_hit": row["keyword_hit"],
        "comparison_coverage": row["comparison_coverage"],
        "latency_ms": row["latency_ms"],
        "matched_terms": ";".join(row["matched_terms"]),  # type: ignore[arg-type]
        "retrieved": ";".join(row["retrieved_ids"]),  # type: ignore[arg-type]
        "cited": ";".join(item["id"] for item in row["citations"]),  # type: ignore[union-attr]
        "refusal_reason": row["refusal_reason"],
        "answer_first_line": excerpt.split("\n")[0][:120],
    }


def summarize(rows: list[dict[str, object]], questions_path: Path) -> dict[str, object]:
    answerable = [row for row in rows if row["expected_type"] != "refusal"]
    hit_eligible = [row for row in rows if row["hit_eligible"]]
    hit_values = [bool(row["retrieval_hit"]) for row in hit_eligible]
    comparison_rows = [row for row in rows if row["expected_type"] == "comparison"]
    comparison_covered = sum(1 for row in comparison_rows if row["comparison_coverage"])
    refusal_expected = [row for row in rows if row["expected_type"] == "refusal"]
    correct_refusals = sum(1 for row in refusal_expected if row["refused"])
    false_refusals = sum(1 for row in answerable if row["refused"])
    citation_total = sum(int(row["citation_total"]) for row in rows)
    citation_valid = sum(int(row["citation_valid"]) for row in rows)
    keyword_rows = [row for row in rows if row["expected_keywords"]]
    keyword_hits = sum(1 for row in keyword_rows if row["keyword_hit"])
    latencies = [float(row["latency_ms"]) for row in rows]
    return {
        "n_questions": len(rows),
        "n_answerable": len(answerable),
        "n_refusal_expected": len(refusal_expected),
        "n_hit_eligible": len(hit_eligible),
        "hit_scope": "聚合类 + 证据类（8 题）；对比类不参与 hit@5，另见 comparison_coverage",
        "retrieval_hit_at_5": round(sum(hit_values) / len(hit_values), 4) if hit_values else 0.0,
        "retrieval_hit_at_5_detail": f"{sum(hit_values)}/{len(hit_values)}",
        "comparison_coverage": round(comparison_covered / len(comparison_rows), 4)
        if comparison_rows
        else None,
        "comparison_coverage_detail": f"{comparison_covered}/{len(comparison_rows)}",
        "citation_total": citation_total,
        "citation_valid": citation_valid,
        "citation_valid_rate": round(citation_valid / citation_total, 4) if citation_total else 0.0,
        "refusal_accuracy": round(correct_refusals / len(refusal_expected), 4)
        if refusal_expected
        else 0.0,
        "refusal_accuracy_detail": f"{correct_refusals}/{len(refusal_expected)}",
        "false_refusal_rate": round(false_refusals / len(answerable), 4) if answerable else 0.0,
        "false_refusal_detail": f"{false_refusals}/{len(answerable)}",
        "intent_match_rate": round(
            sum(1 for row in rows if row["intent_match"]) / len(rows), 4
        ),
        "keyword_match_rate": round(keyword_hits / len(keyword_rows), 4)
        if keyword_rows
        else 0.0,
        "keyword_match_detail": f"{keyword_hits}/{len(keyword_rows)}",
        "latency_ms": _latency_summary(latencies),
        "questions_file": _relative(questions_path),
    }


# ---------------------------------------------------------------------------
# 真实数据冒烟（可选）
# ---------------------------------------------------------------------------


def _int_or(value: object, default: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def seed_real_corpus(
    csv_path: Path,
    database: Path,
    *,
    include_adversarial: bool = False,
) -> dict[str, object]:
    """把真实标注集当检索语料灌进临时库。

    刻意不使用 golden_category / golden_impact_level（避免标签泄漏）：
    category / impact_level / confidence / reason 全部由项目内置的
    RuleClassifier 对 feedback_text + rating 现场计算，模拟"已分类的真实反馈"。

    默认过滤 source 以 authored-adversarial 开头的人工注入探针（2 条）：
    它们不是真实评论，且含 prompt injection 文本；如需单列报告可用
    --real-include-adversarial 打开。
    """
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()
    repository = VoiceBoardRepository(database)
    repository.initialize()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    classifier = RuleClassifier()
    records: list[dict[str, object]] = []
    skipped_adversarial = 0
    predicted_categories: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        source = (row.get("source") or "").strip()
        if not include_adversarial and source.startswith("authored-adversarial"):
            skipped_adversarial += 1
            continue
        eval_id = (row.get("eval_id") or f"R{index:03d}").strip()
        text = (row.get("feedback_text") or "").strip() or "（空文本）"
        rating = max(1, min(5, _int_or(row.get("rating"), 3)))
        classification = classifier.classify(
            {"feedback_text": text, "rating": rating}
        )
        predicted_categories[classification.category] += 1
        records.append(
            {
                "fingerprint": f"agent-real-{eval_id}",
                "feedback_id": eval_id,
                "feedback_text": text,
                "country": (row.get("country") or "UNKNOWN").strip() or "UNKNOWN",
                "user_type": (row.get("user_type") or "未知").strip() or "未知",
                "product_category": (row.get("product_category") or "未标注").strip()
                or "未标注",
                "rating": rating,
                "created_at": (row.get("created_at") or "2026-01-01").strip(),
                "category": classification.category,
                "impact_level": max(1, min(5, int(classification.impact_level))),
                "classification_source": classification.source,
                "confidence": float(classification.confidence),
                "classification_reason": classification.reason,
            }
        )
    repository.import_feedback(
        "agent_real_corpus.csv", "rule", len(records), records
    )
    return {
        "records": len(records),
        "skipped_adversarial": skipped_adversarial,
        "include_adversarial": include_adversarial,
        "label_source": (
            "项目内置 RuleClassifier 现场分类（仅用 feedback_text/rating，"
            "不使用 golden_category / golden_impact_level，避免标签泄漏）；"
            "impact_level 为规则推导值（由 rating 推导 + 高影响词加成），不是人工影响度标签"
        ),
        "country_semantics": (
            "真实集的 country 不是评论者自报，而是按 App 主要市场推断的中文名"
            "（AliExpress/Alibaba=多国（跨境）、Amazon Shopping=美国、印度电商 App=印度、"
            "中文购物语料=中国）；检索层已做中文名↔canonical code 校正"
            "（印度→IN、美国→US、中国→CN，多国（跨境）→GLOBAL 跨境专列，不并入单一国家）"
        ),
        "category_predictions": dict(sorted(predicted_categories.items())),
    }


def run_real_smoke(
    csv_path: Path,
    database: Path,
    *,
    top_k: int = DEFAULT_TOP_K,
    include_adversarial: bool = False,
) -> dict[str, object]:
    seeding = seed_real_corpus(
        csv_path, database, include_adversarial=include_adversarial
    )
    per_question = []
    for question in REAL_SMOKE_QUESTIONS:
        answer = answer_question(question, database, top_k=top_k)
        retrieved_ids = [item.display_id for item in answer.evidence]
        per_question.append(
            {
                "question": question,
                "refused": answer.refused,
                "refusal_reason": answer.refusal_reason,
                "filter_summary": answer.plan.filter_summary(),
                "retrieval_count": len(retrieved_ids),
                "top_ids": retrieved_ids[:5],
                "citation_total": len(answer.citations),
                "citation_valid": sum(
                    1
                    for citation in answer.citations
                    if citation.display_id in retrieved_ids
                    and str(citation.feedback_text).strip()
                ),
                "latency_ms": answer.latency_ms,
                "answer_first_line": _shorten(answer.text, 120),
            }
        )
    with_evidence = sum(1 for item in per_question if item["retrieval_count"] > 0)
    citation_total = sum(int(item["citation_total"]) for item in per_question)
    citation_valid = sum(int(item["citation_valid"]) for item in per_question)
    return {
        "corpus_file": _relative(csv_path),
        **seeding,
        "note": (
            "把真实标注集当检索语料做可用性冒烟：不计算 hit@5（其标签用于分类而非问答），"
            "分类字段由项目内置规则分类器现场生成、不使用 golden 标签，"
            "impact 为由 rating 推导的规则值（非人工标签）；"
            "已默认过滤 2 条 authored-adversarial 注入探针。"
            "真实数据以英文/中英混排为主、国家字段为按市场推断的中文名"
            "（多国（跨境）映射 GLOBAL 跨境专列），中文问题命中率低属于预期（跨语言限制），"
            "详见 docs/agent-scope.md。"
        ),
        "questions": per_question,
        "summary": {
            "n_questions": len(per_question),
            "with_evidence": with_evidence,
            "refused": sum(1 for item in per_question if item["refused"]),
            "citation_valid_rate": round(citation_valid / citation_total, 4)
            if citation_total
            else 0.0,
            "citation_total": citation_total,
            "citation_valid": citation_valid,
            "declared_limitation_questions": [
                item["question"]
                for item in per_question
                if item["retrieval_count"] == 0
            ],
        },
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def run(
    *,
    questions_path: Path = DEFAULT_QUESTIONS,
    out_path: Path = DEFAULT_OUT,
    database: Path | None = None,
    top_k: int = DEFAULT_TOP_K,
    real_corpus: Path | None = None,
    real_db: Path | None = None,
    real_include_adversarial: bool = False,
) -> dict[str, object]:
    started = time.perf_counter()
    questions = load_questions(questions_path)
    if database is None:
        working_dir = Path(tempfile.mkdtemp(prefix="voiceboard-agent-eval-"))
        database = working_dir / "agent_eval.db"
    seed_fixture_database(database)
    rows = [
        evaluate_question(question, database, top_k=top_k) for question in questions
    ]
    category_counts = Counter(str(item["category"]) for item in EVAL_CORPUS)
    country_counts = Counter(str(item["country"]) for item in EVAL_CORPUS)
    dates = sorted(str(item["created"]) for item in EVAL_CORPUS)
    result: dict[str, object] = {
        "schema_version": 1,
        "run_id": f"agent-v1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "template-deterministic",
        "engine": {
            "retrieval": "SQLite 维度过滤 + 中文 bigram + BM25(k1=1.5,b=0.75)",
            "answer": "确定性模板（聚合/证据/对比/拒答），无 LLM、无向量库",
            "llm": False,
        },
        "corpus": {
            "source": "builtin_fixture",
            "file": None,
            "records": len(EVAL_CORPUS),
            "categories": dict(sorted(category_counts.items())),
            "countries": dict(sorted(country_counts.items())),
            "date_range": [dates[0], dates[-1]],
            "note": (
                "确定性评测语料（30 条自造中文跨境电商反馈），用于机制回归与可复现评测，"
                "不是真实用户数据，数字不代表线上效果；真实数据可用性冒烟见 real_data_smoke。"
            ),
        },
        "questions": {
            "file": _relative(questions_path),
            "n": len(questions),
            "types": dict(
                sorted(Counter(str(item["expected_type"]) for item in questions).items())
            ),
        },
        "config": {
            "top_k": top_k,
            "bm25": {"k1": 1.5, "b": 0.75},
            "intent_map": {key: list(value) for key, value in EXPECTED_TYPE_TO_INTENTS.items()},
            "llm_enabled": False,
        },
        "metrics": summarize(rows, questions_path),
        "per_question": [_public_row(row) for row in rows],
        "limitations": [
            "受控小语料（30 条）且问题与语料同源设计，hit@5 偏乐观，不能当线上效果。",
            "hit@5 只在 8 条依赖排序检索的题目上计算；3 条对比题由维度过滤+SQL 聚合出答案，"
            "因此改用 comparison_coverage 检查两侧覆盖与引用，避免对已过滤候选做无信息 hit 判定。",
            "纯字面匹配：同义改写（如“钱退不回来”）检索不到“退款”，q06 是已知 badcase（误拒答）。",
            "不跨语言：中文问题检索英文反馈会命中很低（真实评测集多为英文/中英混排）。",
            "真实数据冒烟（78 条真实评论）只验证「能检索/能引用/能拒答」，没有问答级标注，不算 hit@5；"
            "且真实数据的 country 是按 App 主要市场推断的中文名（印度/美国/中国/多国跨境），检索层已加"
            "「库内实际取值校正」（多国（跨境）→GLOBAL 跨境专列，不并入单一国家），"
            "但“未标注”这类非国家取值无法按国家过滤。",
            "真实数据默认过滤 2 条 authored-adversarial 注入探针（非真实评论）；"
            "如果把它们放进 LLM prompt，属于 prompt injection 风险，当前 LLM 路径默认关闭。",
            "未做 embedding/向量库/语义 rerank，也未做多轮追问、权限隔离与线上埋点。",
            "延迟是本机单进程模板路径的 wall time，不含 Streamlit 渲染和真实网络。",
        ],
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    if real_corpus is not None and real_corpus.exists():
        if real_db is None:
            real_db = database.parent / "agent_real_eval.db"
        result["real_data_smoke"] = run_real_smoke(
            real_corpus,
            real_db,
            top_k=top_k,
            include_adversarial=real_include_adversarial,
        )
    elif real_corpus is not None:
        result["real_data_smoke"] = {
            "corpus_file": str(real_corpus),
            "error": "文件不存在，未运行真实数据冒烟",
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _print_summary(result: dict[str, object]) -> None:
    metrics = result["metrics"]  # type: ignore[assignment]
    latency = metrics["latency_ms"]  # type: ignore[index]
    corpus = result["corpus"]  # type: ignore[assignment]
    print(
        f"agent_eval mode={result['mode']} corpus={corpus['source']}"
        f"({corpus['records']}) questions={metrics['n_questions']}"
    )
    print(
        f"hit@5={metrics['retrieval_hit_at_5']:.3f} ({metrics['retrieval_hit_at_5_detail']})"
        f" comparison_coverage={metrics['comparison_coverage']}"
        f" citations={metrics['citation_valid']}/{metrics['citation_total']}"
        f" ({metrics['citation_valid_rate']:.3f})"
    )
    print(
        f"refusal_acc={metrics['refusal_accuracy']:.3f}"
        f" ({metrics['refusal_accuracy_detail']})"
        f" false_refusal={metrics['false_refusal_rate']:.3f}"
        f" ({metrics['false_refusal_detail']})"
        f" intent={metrics['intent_match_rate']:.3f}"
        f" keyword={metrics['keyword_match_rate']:.3f}"
        f" ({metrics['keyword_match_detail']})"
    )
    print(
        f"latency p50={latency['p50']}ms p95={latency['p95']}ms"
        f" mean={latency['mean']}ms max={latency['max']}ms"
    )
    if "real_data_smoke" in result:
        smoke = result["real_data_smoke"]
        if isinstance(smoke, dict) and "summary" in smoke:
            summary = smoke["summary"]
            print(
                f"real_smoke records={smoke['records']}"
                f" skipped_adversarial={smoke.get('skipped_adversarial', 0)}"
                f" with_evidence={summary['with_evidence']}"
                f"/{summary['n_questions']} cited_valid={summary['citation_valid']}"
                f"/{summary['citation_total']}"
            )
        else:
            print(f"real_smoke skipped: {smoke}")
    print(f"out={result.get('out_path', '')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行反馈问答 Agent 的 15 题离线评测")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--db", type=Path, default=None, help="评测用临时 SQLite 路径")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--real-corpus",
        type=Path,
        default=None,
        help="可选：真实标注集 CSV，作为检索语料跑 6 条冒烟问题（不使用 golden 标签）",
    )
    parser.add_argument("--real-db", type=Path, default=None)
    parser.add_argument(
        "--real-include-adversarial",
        action="store_true",
        help="默认过滤 authored-adversarial 注入探针；加上则把 2 条探针也放入语料",
    )
    args = parser.parse_args(argv)
    result = run(
        questions_path=args.questions,
        out_path=args.out,
        database=args.db,
        top_k=args.top_k,
        real_corpus=args.real_corpus,
        real_db=args.real_db,
        real_include_adversarial=args.real_include_adversarial,
    )
    _print_summary({**result, "out_path": _relative(args.out)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
