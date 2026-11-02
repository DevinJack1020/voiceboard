from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from src.repository import VoiceBoardRepository
from src.services.evaluation_service import (
    BADCASE_LAYERS,
    DASH,
    Badcase,
    EvaluationService,
    available_result_files,
    badcase_layer_counts,
    build_evaluation_result,
    collect_revision_statistics,
    filter_badcases,
    format_cny,
    format_decimal,
    format_int,
    format_ms,
    format_percent,
    format_tokens,
    load_badcases,
    load_evaluation_result,
    load_evaluation_results,
    load_result_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEEPSEEK_PAYLOAD = {
    "run_id": "deepseek_v1-20261102",
    "mode": "deepseek",
    "model": "deepseek-chat",
    "prompt_version": "prompt-v1",
    "dataset": "evals/feedback_eval_v1.csv",
    "n": 10,
    "timestamp": "2026-11-02T10:00:00+08:00",
    "metrics": {
        "accuracy_business": 0.9,
        "accuracy_e2e": 0.8,
        "macro_recall_business": 0.85,
        "key_class_recall": {"物流": 0.75, "支付": 1.0, "商品质量": 0.5},
        "per_class": {
            "物流": {"precision": 1.0, "recall": 0.75, "f1": 0.857, "support": 4},
            "支付": {"precision": 0.8, "recall": 1.0, "f1": 0.888, "support": 2},
            "待确认": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 2},
        },
        "confusion_matrix": {
            "物流": {"物流": 3, "待确认": 1},
            "支付": {"支付": 2},
            "待确认": {"待确认": 1, "支付": 1},
        },
        "uncertain_count": 2,
        "uncertain_rate": 0.2,
        "business_to_uncertain_rate": 0.1,
        "uncertain_to_business_rate": 0.1,
        "human_revision_rate_estimate": 0.15,
        "impact_mae": 0.4,
        "impact_exact_rate": 0.7,
    },
    "cost": {
        "prompt_tokens": 5000,
        "completion_tokens": 1200,
        "total_tokens": 6200,
        "estimated_cny": 0.0123,
        "pricing_note": "按官方单价与实测 token 估算",
    },
    "latency": {
        "p50_ms": 850.0,
        "p95_ms": 1600.0,
        "mean_ms": 900.0,
        "total_s": 12.3,
        "n_errors": 0,
    },
    "failures": [],
}

RULE_PAYLOAD = {
    "run_id": "rule_v1-20261102",
    "mode": "rule",
    "model": "rule-keyword-v1",
    "prompt_version": "n/a",
    "dataset": "evals/feedback_eval_v1.csv",
    "n": 10,
    "timestamp": "2026-11-02T09:30:00+08:00",
    "metrics": {
        "accuracy_business": 0.6,
        "accuracy_e2e": 0.5,
        "macro_recall_business": 0.55,
        "key_class_recall": {"物流": 0.5, "支付": 0.5, "商品质量": 0.0},
        "per_class": {"物流": {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 2}},
        "confusion_matrix": {"物流": {"物流": 1, "支付": 1}},
        "uncertain_count": 3,
        "uncertain_rate": 0.3,
        "human_revision_rate_estimate": 0.25,
        "impact_mae": 0.9,
        "impact_exact_rate": 0.4,
    },
    "cost": {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cny": 0.0,
        "pricing_note": "规则分类无 API 成本",
    },
    "latency": {
        "p50_ms": 0.03,
        "p95_ms": 0.1,
        "mean_ms": 0.05,
        "total_s": 0.0005,
        "n_errors": 0,
    },
    "failures": [],
}

BADCASE_COLUMNS = (
    "eval_id",
    "feedback_text",
    "golden_category",
    "predicted_category",
    "confidence",
    "layer",
    "reason",
    "proposed_fix",
)

BADCASE_ROWS = [
    {
        "eval_id": "eval-001",
        "feedback_text": "物流太慢，等了两周",
        "golden_category": "物流",
        "predicted_category": "待确认",
        "confidence": "0.42",
        "layer": "数据",
        "reason": "golden 为物流但原文缺少订单上下文",
        "proposed_fix": "补充物流上下文列",
    },
    {
        "eval_id": "eval-002",
        "feedback_text": "支付失败但又说物流慢",
        "golden_category": "支付",
        "predicted_category": "物流",
        "confidence": "0.55",
        "layer": "提示词",
        "reason": "多意图未被 prompt 覆盖",
        "proposed_fix": "提示词增加主痛点判定规则",
    },
    {
        "eval_id": "eval-003",
        "feedback_text": "退款到账慢",
        "golden_category": "退换货",
        "predicted_category": "物流",
        "confidence": "0.61",
        "layer": "规则",
        "reason": "关键词“慢”误命中物流",
        "proposed_fix": "降低通用词权重",
    },
    {
        "eval_id": "eval-004",
        "feedback_text": "客服不回复",
        "golden_category": "客服",
        "predicted_category": "待确认",
        "confidence": "0.3",
        "layer": "交互",
        "reason": "低置信度直接进入待确认，缺少人工复核提示",
        "proposed_fix": "待确认列表增加复核入口",
    },
]


def _write_json(directory: Path, name: str, payload: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...] | list[str],
    rows: list[dict[str, object]],
    *,
    encoding: str = "utf-8",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text(buffer.getvalue(), encoding=encoding)
    return path


def _write_badcases(directory: Path, rows=None, *, encoding: str = "utf-8") -> Path:
    return _write_csv(
        directory / "badcases_v1.csv",
        BADCASE_COLUMNS,
        BADCASE_ROWS if rows is None else rows,
        encoding=encoding,
    )


def _make_repository(path: Path) -> VoiceBoardRepository:
    repository = VoiceBoardRepository(path)
    repository.initialize()
    return repository


def _record(
    fingerprint: str,
    category: str,
    source: str,
    product_category: str = "电子产品",
    text: str | None = None,
) -> dict[str, object]:
    return {
        "fingerprint": fingerprint,
        "feedback_id": None,
        "feedback_text": text or f"反馈内容 {fingerprint}",
        "country": "SG",
        "user_type": "新用户",
        "product_category": product_category,
        "rating": 3,
        "created_at": "2026-10-20",
        "category": category,
        "impact_level": 3,
        "classification_source": source,
        "confidence": 0.8,
        "classification_reason": "测试数据",
    }


def _insert_feedback(
    repository: VoiceBoardRepository, records: list[dict[str, object]]
) -> None:
    batch_id = repository.create_import_batch("feedback.csv", "rule", len(records))
    repository.insert_feedback_batch(batch_id, records)


def _feedback_ids(repository: VoiceBoardRepository) -> dict[str, int]:
    rows, _ = repository.query_feedback({}, limit=1000)
    return {str(row["fingerprint"]): int(row["id"]) for row in rows}


# ---------------------------------------------------------------------------
# 结果 JSON 读取与容错
# ---------------------------------------------------------------------------


def test_loads_deepseek_result_and_normalizes_metrics(tmp_path):
    path = _write_json(tmp_path, "deepseek_v1.json", DEEPSEEK_PAYLOAD)

    result = load_result_file(path)

    assert result is not None
    assert result.run_id == "deepseek_v1-20261102"
    assert result.mode == "deepseek"
    assert result.model == "deepseek-chat"
    assert result.prompt_version == "prompt-v1"
    assert result.dataset == "evals/feedback_eval_v1.csv"
    assert result.n == 10
    assert result.dataset_size == 10
    assert result.metric_number("accuracy_business") == pytest.approx(0.9)
    assert result.metric_number("accuracy_e2e") == pytest.approx(0.8)
    assert result.metric_number("macro_recall_business") == pytest.approx(0.85)
    assert result.key_class_recall["物流"] == pytest.approx(0.75)
    assert set(result.per_class) == {"物流", "支付", "待确认"}
    assert result.per_class["物流"]["support"] == 4
    assert result.confusion_matrix["物流"]["待确认"] == 1
    assert result.cost_number("total_tokens") == 6200
    assert result.cost_number("estimated_cny") == pytest.approx(0.0123)
    assert result.latency_number("p95_ms") == pytest.approx(1600.0)
    assert result.pricing_note
    assert result.failures == ()
    assert "DeepSeek" in result.label
    assert result.source_path == path


def test_result_fallback_order_and_available_files(tmp_path):
    directory = tmp_path / "results"

    assert load_evaluation_result(directory) is None
    assert load_evaluation_results(directory) == []
    assert available_result_files(directory) == []

    _write_json(directory, "rule_v1.json", RULE_PAYLOAD)
    (directory / "predictions_rule_v1.csv").write_text(
        "eval_id,predicted_category\n", encoding="utf-8"
    )
    only_rule = load_evaluation_result(directory)
    assert only_rule is not None
    assert only_rule.source_path.name == "rule_v1.json"
    assert "规则基线" in only_rule.label

    _write_json(directory, "deepseek_v1.json", DEEPSEEK_PAYLOAD)
    results = load_evaluation_results(directory)
    assert [result.source_path.name for result in results] == [
        "deepseek_v1.json",
        "rule_v1.json",
    ]
    preferred = load_evaluation_result(directory)
    assert preferred is not None
    assert preferred.mode == "deepseek"

    (directory / "deepseek_v1.json").write_text("{broken json", encoding="utf-8")
    fallback = load_evaluation_result(directory)
    assert fallback is not None
    assert fallback.source_path.name == "rule_v1.json"


def test_corrupt_or_partial_result_is_tolerated(tmp_path):
    directory = tmp_path / "results"
    directory.mkdir()

    (directory / "deepseek_v1.json").write_text("{not json", encoding="utf-8")
    assert load_result_file(directory / "deepseek_v1.json") is None
    (directory / "deepseek_v1.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert load_result_file(directory / "deepseek_v1.json") is None
    (directory / "deepseek_v1.json").write_text("null", encoding="utf-8")
    assert load_result_file(directory / "deepseek_v1.json") is None

    _write_json(directory, "rule_v1.json", {"mode": "rule"})
    partial = load_evaluation_result(directory)
    assert partial is not None
    assert partial.mode == "rule"
    assert partial.metric_number("accuracy_business") is None
    assert partial.dataset_size == 0
    assert partial.per_class == {}
    assert partial.confusion_matrix == {}
    assert partial.key_class_recall == {}
    assert partial.failures == ()
    assert partial.pricing_note == ""
    assert partial.cost_number("total_tokens") is None

    odd = build_evaluation_result(
        Path("odd.json"),
        {
            "run_id": None,
            "n": "not-a-number",
            "metrics": "oops",
            "cost": None,
            "latency": [],
            "failures": "nope",
        },
    )
    assert odd.run_id == ""
    assert odd.n == 0
    assert odd.metrics == {}
    assert odd.cost == {}
    assert odd.latency == {}
    assert odd.failures == ()


def test_partial_metric_fields_are_normalized(tmp_path):
    payload = {
        "mode": "rule",
        "n": "4",
        "metrics": {
            "accuracy_business": "0.5",
            "per_class": {
                "物流": {"precision": "0.5", "recall": None, "f1": 0.75, "support": "4"},
                "坏数据": "not-a-mapping",
            },
            "confusion_matrix": {"物流": {"物流": "3", "支付": None}},
            "key_class_recall": {"物流": None, "支付": 1.0},
        },
        "failures": [{"eval_id": "x", "error": "timeout"}],
    }
    result = build_evaluation_result(tmp_path / "rule_v1.json", payload)

    assert result.n == 4
    assert result.metric_number("accuracy_business") == pytest.approx(0.5)
    assert result.per_class["物流"]["precision"] == pytest.approx(0.5)
    assert result.per_class["物流"]["recall"] is None
    assert result.per_class["物流"]["f1"] == pytest.approx(0.75)
    assert result.per_class["物流"]["support"] == 4
    assert "坏数据" not in result.per_class
    assert result.confusion_matrix["物流"]["物流"] == 3
    assert result.confusion_matrix["物流"]["支付"] == 0
    assert result.key_class_recall["物流"] is None
    assert result.key_class_recall["支付"] == pytest.approx(1.0)
    assert result.dataset_size == 4
    assert result.failures == ({"eval_id": "x", "error": "timeout"},)


# ---------------------------------------------------------------------------
# Badcase CSV 读取与筛选
# ---------------------------------------------------------------------------


def test_load_badcases_reads_csv_and_tolerates_missing_fields(tmp_path):
    path = _write_badcases(tmp_path, encoding="utf-8-sig")

    cases = load_badcases(path)

    assert [case.eval_id for case in cases] == [
        "eval-001",
        "eval-002",
        "eval-003",
        "eval-004",
    ]
    assert cases[0].feedback_text == "物流太慢，等了两周"
    assert cases[0].layer == "数据"
    assert cases[0].confidence == pytest.approx(0.42)
    assert cases[1].proposed_fix == "提示词增加主痛点判定规则"

    partial_path = _write_csv(
        tmp_path / "partial.csv",
        ["eval_id", "feedback_text", "layer"],
        [
            {"eval_id": "eval-009", "feedback_text": "只有三列", "layer": "交互"},
            {"eval_id": "eval-010", "feedback_text": "置信度缺失", "layer": ""},
        ],
    )
    partial = load_badcases(partial_path)
    assert len(partial) == 2
    assert partial[0].golden_category == ""
    assert partial[0].predicted_category == ""
    assert partial[0].confidence is None
    assert partial[0].reason == ""
    assert partial[0].proposed_fix == ""
    assert partial[1].layer_label == "未归因"


def test_load_badcases_returns_empty_for_missing_empty_or_bad_encoding(tmp_path):
    assert load_badcases(tmp_path / "missing.csv") == []

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    assert load_badcases(empty) == []

    header_only = _write_csv(tmp_path / "header.csv", ["eval_id"], [])
    assert load_badcases(header_only) == []


def test_filter_badcases_and_layer_counts():
    cases = [
        Badcase("1", "a", "物流", "待确认", 0.4, "数据", "r", "f"),
        Badcase("2", "b", "支付", "物流", 0.5, "提示词", "r", "f"),
        Badcase("3", "c", "退换货", "物流", 0.6, "规则", "r", "f"),
        Badcase("4", "d", "客服", "待确认", 0.3, "交互", "r", "f"),
        Badcase("5", "e", "物流", "物流", None, "", "", ""),
    ]

    assert len(filter_badcases(cases, None)) == 5
    assert len(filter_badcases(cases, "全部")) == 5
    assert [case.eval_id for case in filter_badcases(cases, "数据")] == ["1"]
    assert filter_badcases(cases, "不存在") == []

    counts = badcase_layer_counts(cases)
    assert counts == {"数据": 1, "提示词": 1, "规则": 1, "交互": 1}
    assert tuple(counts) == BADCASE_LAYERS


# ---------------------------------------------------------------------------
# 运行时人工修订统计
# ---------------------------------------------------------------------------


def test_empty_database_returns_zero_statistics(tmp_path):
    repository = _make_repository(tmp_path / "voiceboard.db")

    stats = collect_revision_statistics(repository)

    assert stats.total_feedback == 0
    assert stats.classified_count == 0
    assert stats.uncertain_count == 0
    assert stats.uncertain_rate == 0.0
    assert stats.revision_count == 0
    assert stats.revised_feedback_count == 0
    assert stats.human_revision_rate == 0.0
    assert [row.source for row in stats.by_source] == ["rule", "deepseek", "manual"]
    assert all(row.total == 0 and row.revision_rate == 0.0 for row in stats.by_source)
    assert stats.uncertain_by_product_category == ()
    assert stats.category_shares == ()


def test_missing_database_file_returns_zero_statistics(tmp_path):
    stats = collect_revision_statistics(tmp_path / "not-created" / "voiceboard.db")

    assert stats.total_feedback == 0
    assert stats.classified_count == 0
    assert stats.human_revision_rate == 0.0


def test_revision_statistics_after_manual_revisions(tmp_path):
    repository = _make_repository(tmp_path / "voiceboard.db")
    _insert_feedback(
        repository,
        [
            _record("f1", "物流", "rule", text="物流太慢"),
            _record("f2", "待确认", "rule", text="看不懂在说什么"),
            _record("f3", "支付", "deepseek", "服饰", text="支付失败"),
            _record("f4", "商品质量", "deepseek", "电子产品", text="质量差"),
            _record("f5", "搜索推荐", "manual", "服饰", text="推荐不准"),
        ],
    )
    ids = _feedback_ids(repository)
    repository.revise_feedback(ids["f1"], "支付", 4, "人工核对：物流改为支付")
    repository.revise_feedback(ids["f1"], "客服", 4, "再次核对：支付改为客服")
    repository.revise_feedback(ids["f3"], "客服", 5, "人工核对：支付改为客服")

    stats = collect_revision_statistics(repository)

    assert stats.total_feedback == 5
    assert stats.classified_count == 5
    assert stats.uncertain_count == 1
    assert stats.uncertain_rate == pytest.approx(0.2)
    assert stats.revision_count == 3
    assert stats.revised_feedback_count == 2
    assert stats.human_revision_rate == pytest.approx(0.4)

    by_source = {row.source: row for row in stats.by_source}
    assert by_source["rule"].total == 1
    assert by_source["rule"].revised == 0
    assert by_source["deepseek"].total == 1
    assert by_source["deepseek"].revised == 0
    assert by_source["manual"].total == 3
    assert by_source["manual"].revised == 2
    assert by_source["manual"].revision_rate == pytest.approx(2 / 3)

    by_product = {row.product_category: row for row in stats.uncertain_by_product_category}
    assert by_product["电子产品"].total == 3
    assert by_product["电子产品"].uncertain == 1
    assert by_product["电子产品"].uncertain_rate == pytest.approx(1 / 3)
    assert by_product["服饰"].total == 2
    assert by_product["服饰"].uncertain == 0
    assert by_product["服饰"].uncertain_rate == 0.0

    shares = {row.category: row for row in stats.category_shares}
    assert shares["待确认"].count == 1
    assert shares["待确认"].share == pytest.approx(0.2)
    assert shares["客服"].count == 2


def test_revision_statistics_parameterize_free_text_values(tmp_path):
    repository = _make_repository(tmp_path / "voiceboard.db")
    tricky_product = "电子'产品\" OR 1=1 --"
    _insert_feedback(
        repository,
        [_record("sql-1", "待确认", "rule", tricky_product)],
    )

    stats = collect_revision_statistics(repository)

    assert stats.total_feedback == 1
    assert stats.uncertain_count == 1
    assert [row.product_category for row in stats.uncertain_by_product_category] == [
        tricky_product
    ]


def test_service_facade_reads_fixture_directory(tmp_path, monkeypatch):
    directory = tmp_path / "results"
    _write_json(directory, "deepseek_v1.json", DEEPSEEK_PAYLOAD)
    _write_json(directory, "rule_v1.json", RULE_PAYLOAD)
    _write_badcases(directory)
    repository = _make_repository(tmp_path / "voiceboard.db")

    service = EvaluationService(repository, results_dir=directory)

    assert [item.mode for item in service.load_results()] == ["deepseek", "rule"]
    assert service.load_result() is not None
    assert len(service.load_badcases()) == 4
    assert service.revision_statistics().total_feedback == 0

    monkeypatch.setenv("VOICEBOARD_EVAL_DIR", str(directory))
    env_service = EvaluationService(repository)
    assert env_service.load_result() is not None
    assert len(env_service.load_badcases()) == 4


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def test_formatting_helpers_keep_missing_values_honest():
    assert format_percent(0.875) == "87.5%"
    assert format_percent(None) == DASH
    assert format_percent("bad") == DASH
    assert format_decimal(0.1234, 3) == "0.123"
    assert format_int(6200) == "6,200"
    assert format_int(None) == DASH
    assert format_ms(1234.6) == "1,235 ms"
    assert format_ms(None) == DASH
    assert format_tokens(6200) == "6,200"
    assert format_tokens(None) == DASH
    assert format_cny(0.0123) == "¥0.0123"
    assert format_cny(12.34) == "¥12.34"
    assert format_cny(None) == DASH
