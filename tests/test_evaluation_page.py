from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.repository import VoiceBoardRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_PAGE = PROJECT_ROOT / "pages" / "6_评测与Badcase.py"
FEEDBACK_PAGE = PROJECT_ROOT / "pages" / "2_反馈明细.py"

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
        "per_class": {
            "物流": {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 2}
        },
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


def _write_json(directory: Path, name: str, payload: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_badcases(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(BADCASE_COLUMNS))
    writer.writeheader()
    for row in BADCASE_ROWS:
        writer.writerow(row)
    (directory / "badcases_v1.csv").write_text(
        buffer.getvalue(), encoding="utf-8-sig"
    )


def _record(
    fingerprint: str,
    text: str,
    category: str,
    source: str,
    product_category: str = "电子产品",
) -> dict[str, object]:
    return {
        "fingerprint": fingerprint,
        "feedback_id": None,
        "feedback_text": text,
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


def _seed_database(database: Path) -> VoiceBoardRepository:
    """5 条反馈 + 2 条人工修订：修订率 = 2/5 = 40%，待确认占比 = 1/5 = 20%。"""
    repository = VoiceBoardRepository(database)
    repository.initialize()
    records = [
        _record("f-rule-logistics", "物流太慢，等了两周", "物流", "rule"),
        _record("f-rule-uncertain", "看不懂这是在说什么", "待确认", "rule"),
        _record("f-deepseek-payment", "支付失败，钱扣了", "支付", "deepseek", "服饰"),
        _record("f-deepseek-quality", "质量差，有异味", "商品质量", "deepseek"),
        _record("f-manual-search", "推荐不准，找不到想要的", "搜索推荐", "manual", "服饰"),
    ]
    batch_id = repository.create_import_batch("feedback.csv", "rule", len(records))
    repository.insert_feedback_batch(batch_id, records)
    rows, _ = repository.query_feedback({}, limit=100)
    ids = {str(row["fingerprint"]): int(row["id"]) for row in rows}
    repository.revise_feedback(ids["f-rule-logistics"], "支付", 4, "人工核对：物流改为支付")
    repository.revise_feedback(ids["f-deepseek-payment"], "客服", 5, "人工核对：支付改为客服")
    return repository


def _fixture_environment(tmp_path: Path, monkeypatch) -> Path:
    results_dir = tmp_path / "results"
    _write_json(results_dir, "deepseek_v1.json", DEEPSEEK_PAYLOAD)
    _write_json(results_dir, "rule_v1.json", RULE_PAYLOAD)
    _write_badcases(results_dir)
    monkeypatch.setenv("VOICEBOARD_EVAL_DIR", str(results_dir))
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))
    _seed_database(tmp_path / "voiceboard.db")
    return results_dir


def _metric_value(app: AppTest, label: str) -> str:
    for metric in app.metric:
        if metric.label == label:
            return str(metric.value)
    labels = [metric.label for metric in app.metric]
    raise AssertionError(f"缺少指标卡“{label}”，当前指标卡：{labels}")


def _all_text(app: AppTest) -> str:
    parts: list[str] = []
    for attribute in (
        "title",
        "subheader",
        "markdown",
        "caption",
        "warning",
        "info",
        "error",
        "code",
    ):
        for element in getattr(app, attribute):
            parts.append(str(getattr(element, "value", "")))
    return "\n".join(parts)


def test_evaluation_page_has_an_honest_empty_state(tmp_path, monkeypatch):
    empty_results = tmp_path / "results"
    empty_results.mkdir()
    monkeypatch.setenv("VOICEBOARD_EVAL_DIR", str(empty_results))
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(EVALUATION_PAGE))
    app.run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "评测与 Badcase"
    warning_text = "\n".join(warning.value for warning in app.warning)
    assert "没有找到" in warning_text
    assert "不代表线上效果" in warning_text
    assert any("run_eval.py" in code.value for code in app.code)
    assert any("还没有导入反馈" in info.value for info in app.info)
    assert len(app.metric) == 0


def test_evaluation_page_renders_metrics_tables_and_badcases(tmp_path, monkeypatch):
    _fixture_environment(tmp_path, monkeypatch)

    app = AppTest.from_file(str(EVALUATION_PAGE))
    app.run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "评测与 Badcase"

    assert _metric_value(app, "评测样本") == "10"
    assert _metric_value(app, "业务类准确率") == "90.0%"
    assert _metric_value(app, "端到端准确率") == "80.0%"
    assert _metric_value(app, "Macro Recall（业务类）") == "85.0%"
    assert _metric_value(app, "关键类召回 · 物流") == "75.0%"
    assert _metric_value(app, "关键类召回 · 支付") == "100.0%"
    assert _metric_value(app, "关键类召回 · 商品质量") == "50.0%"
    assert _metric_value(app, "待确认率") == "20.0%"
    assert _metric_value(app, "人工修订率估计") == "15.0%"
    assert _metric_value(app, "p50 延迟") == "850 ms"
    assert _metric_value(app, "p95 延迟") == "1,600 ms"
    assert _metric_value(app, "总 token") == "6,200"
    assert _metric_value(app, "估算成本") == "¥0.0123"

    text = _all_text(app)
    assert "每类 Precision / Recall / F1" in text
    assert "混淆矩阵" in text
    assert "不代表线上效果" in text
    assert "单标注者" in text
    assert any("共 4 条 Badcase" in caption.value for caption in app.caption)
    assert len(app.dataframe) >= 4
    assert len(app.radio) == 1
    assert any("DeepSeek" in option for option in app.radio[0].options)

    layer_selectbox = next(
        selectbox
        for selectbox in app.selectbox
        if selectbox.label == "按归因层级筛选"
    )
    assert layer_selectbox.options == ["全部", "数据", "提示词", "规则", "交互"]

    # 运行时人工修订统计（来自 SQLite）
    assert _metric_value(app, "已分类反馈") == "5"
    assert _metric_value(app, "待确认反馈") == "1"
    assert _metric_value(app, "待确认占比") == "20.0%"
    assert _metric_value(app, "有修订记录的反馈") == "2"
    assert _metric_value(app, "人工修订率") == "40.0%"


def test_evaluation_page_filters_badcases_by_layer(tmp_path, monkeypatch):
    _fixture_environment(tmp_path, monkeypatch)
    app = AppTest.from_file(str(EVALUATION_PAGE))
    app.run(timeout=20)

    layer_selectbox = next(
        selectbox
        for selectbox in app.selectbox
        if selectbox.label == "按归因层级筛选"
    )
    layer_selectbox.set_value("提示词")
    app.run(timeout=20)

    assert not app.exception
    assert any("共 1 条 Badcase" in caption.value for caption in app.caption)


def test_evaluation_page_can_switch_to_rule_baseline(tmp_path, monkeypatch):
    _fixture_environment(tmp_path, monkeypatch)
    app = AppTest.from_file(str(EVALUATION_PAGE))
    app.run(timeout=20)

    rule_option = next(
        option for option in app.radio[0].options if "rule_v1.json" in option
    )
    app.radio[0].set_value(rule_option)
    app.run(timeout=20)

    assert not app.exception
    assert _metric_value(app, "业务类准确率") == "60.0%"


def test_evaluation_page_rule_only_fallback_without_badcases(tmp_path, monkeypatch):
    results_dir = tmp_path / "results"
    _write_json(results_dir, "rule_v1.json", RULE_PAYLOAD)
    monkeypatch.setenv("VOICEBOARD_EVAL_DIR", str(results_dir))
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(EVALUATION_PAGE))
    app.run(timeout=20)

    assert not app.exception
    assert _metric_value(app, "业务类准确率") == "60.0%"
    assert len(app.radio) == 0
    assert any("还没有 Badcase 记录" in info.value for info in app.info)
    assert any("还没有导入反馈" in info.value for info in app.info)
    assert all(metric.label != "已分类反馈" for metric in app.metric)


def test_feedback_page_shows_revision_statistics_row(tmp_path, monkeypatch):
    database = tmp_path / "voiceboard.db"
    _seed_database(database)
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(database))

    app = AppTest.from_file(str(FEEDBACK_PAGE))
    app.run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "反馈明细"
    assert _metric_value(app, "已分类反馈") == "5"
    assert _metric_value(app, "待确认反馈") == "1"
    assert _metric_value(app, "待确认占比") == "20.0%"
    assert _metric_value(app, "人工修订率") == "40.0%"
    assert any("评测与Badcase" in caption.value for caption in app.caption)
