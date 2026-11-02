"""评测引擎与 DeepSeek 埋点的单元测试（合成标签，不依赖真实数据集与网络）。

覆盖：

- metrics 纯函数：准确率 / 召回 / precision / f1 / 混淆矩阵 / MAE / 待确认比例，
  以及除零、空集、零样本类别等边界。
- latency 分位数与空集。
- cost 官方单价换算、peak/off-peak、未知模型回退。
- attribution 四层启发式与人工覆盖。
- scripts/run_eval.py：数据集校验、rule 运行装配、replay 复算、DeepSeek 失败
  重试与"失败不写正式结果"语义。
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.evaluation.attribution import (
    LAYERS,
    build_badcases,
    category_terms_hit,
    count_layers,
)
from src.evaluation.cost import (
    CNY_PER_MILLION,
    PRICING_SOURCE_URL,
    estimate_batch_cost,
    estimate_cost,
    is_peak,
    pricing_band,
)
from src.evaluation.latency import percentile, summarize_latency
from src.evaluation.metrics import (
    ALL_CATEGORIES,
    BUSINESS_CATEGORIES,
    accuracy,
    accuracy_business,
    compute_metrics,
    confusion_matrix,
    impact_metrics,
    key_class_recall,
    macro_recall_business,
    per_class_metrics,
    uncertain_metrics,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def test_accuracy_counts_exact_matches_and_handles_uncertain():
    goldens = ["物流", "支付", "待确认", "客服"]
    predictions = ["物流", "退换货", "待确认", "客服"]

    assert accuracy(goldens, predictions) == pytest.approx(0.75)
    # 业务类样本：物流/支付/客服（待确认排除）
    assert accuracy_business(goldens, predictions) == pytest.approx(2 / 3)


def test_per_class_precision_recall_f1_with_known_numbers():
    # 物流: TP=1, FP=1(第二条预测物流但 golden 支付), FN=0 -> P=0.5, R=1, F1=2/3
    goldens = ["物流", "支付", "商品质量"]
    predictions = ["物流", "物流", "商品质量"]

    metrics = per_class_metrics(goldens, predictions)

    assert metrics["物流"]["precision"] == pytest.approx(0.5)
    assert metrics["物流"]["recall"] == pytest.approx(1.0)
    assert metrics["物流"]["f1"] == pytest.approx(2 / 3)
    assert metrics["支付"]["recall"] == pytest.approx(0.0)
    assert metrics["支付"]["support"] == 1
    assert metrics["商品质量"]["f1"] == pytest.approx(1.0)
    # 零样本类不抛异常
    assert metrics["搜索推荐"] == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}


def test_macro_recall_and_key_class_recall_cover_six_business_classes():
    goldens = ["物流", "物流", "支付", "客服", "待确认"]
    predictions = ["物流", "退换货", "支付", "待确认", "待确认"]

    # 物流 1/2, 支付 1/1, 客服 0/1，其余 support=0 不参与宏平均
    assert macro_recall_business(goldens, predictions) == pytest.approx((0.5 + 1.0 + 0.0) / 3)
    assert key_class_recall(goldens, predictions) == {
        "物流": pytest.approx(0.5),
        "支付": pytest.approx(1.0),
        "商品质量": pytest.approx(0.0),
    }


def test_confusion_matrix_is_complete_and_counts_pairs():
    goldens = ["物流", "物流", "支付"]
    predictions = ["物流", "支付", "支付"]

    matrix = confusion_matrix(goldens, predictions)

    assert list(matrix) == list(ALL_CATEGORIES)
    assert matrix["物流"]["物流"] == 1
    assert matrix["物流"]["支付"] == 1
    assert matrix["支付"]["支付"] == 1
    assert matrix["物流"]["客服"] == 0
    assert sum(sum(row.values()) for row in matrix.values()) == 3


def test_uncertain_rates_and_human_revision_estimate():
    goldens = ["物流", "支付", "待确认", "待确认", "客服"]
    predictions = ["待确认", "支付", "物流", "待确认", "客服"]

    metrics = uncertain_metrics(goldens, predictions)

    assert metrics["uncertain_count"] == 2
    assert metrics["uncertain_rate"] == pytest.approx(2 / 5)
    # 业务类 3 条里 1 条被降级为待确认
    assert metrics["business_to_uncertain_rate"] == pytest.approx(1 / 3)
    # golden 待确认 2 条里 1 条被强行归入业务类
    assert metrics["uncertain_to_business_rate"] == pytest.approx(1 / 2)
    # 待确认 2 条 + 业务误判 0 条 => 2/5
    assert metrics["human_revision_rate_estimate"] == pytest.approx(2 / 5)


def test_impact_metrics_skip_missing_values_and_handle_empty():
    metrics = impact_metrics([5, 3, None, ""], [4, 3, 2, 1])

    assert metrics["impact_mae"] == pytest.approx(0.5)
    assert metrics["impact_exact_rate"] == pytest.approx(0.5)
    assert impact_metrics([], []) == {"impact_mae": 0.0, "impact_exact_rate": 0.0}
    assert impact_metrics(None, None) == {"impact_mae": 0.0, "impact_exact_rate": 0.0}


def test_empty_inputs_never_divide_by_zero():
    metrics = compute_metrics([], [])

    assert metrics["accuracy_e2e"] == 0.0
    assert metrics["accuracy_business"] == 0.0
    assert metrics["macro_recall_business"] == 0.0
    assert metrics["uncertain_count"] == 0
    assert metrics["uncertain_rate"] == 0.0
    assert metrics["business_to_uncertain_rate"] == 0.0
    assert metrics["uncertain_to_business_rate"] == 0.0
    assert metrics["human_revision_rate_estimate"] == 0.0
    assert metrics["impact_mae"] == 0.0
    assert all(metrics["per_class"][category]["support"] == 0 for category in ALL_CATEGORIES)


def test_compute_metrics_has_stable_schema_order():
    metrics = compute_metrics(["物流"], ["物流"])

    assert list(metrics) == [
        "accuracy_business",
        "accuracy_e2e",
        "macro_recall_business",
        "key_class_recall",
        "per_class",
        "confusion_matrix",
        "uncertain_count",
        "uncertain_rate",
        "business_to_uncertain_rate",
        "uncertain_to_business_rate",
        "human_revision_rate_estimate",
        "impact_mae",
        "impact_exact_rate",
    ]


def test_unknown_labels_are_rejected_loudly():
    with pytest.raises(ValueError, match="未知类别"):
        accuracy(["物流"], ["广告"])
    with pytest.raises(ValueError, match="未知类别"):
        accuracy(["广告"], ["物流"])
    with pytest.raises(ValueError, match="数量不一致"):
        accuracy(["物流"], ["物流", "支付"])


# ---------------------------------------------------------------------------
# latency
# ---------------------------------------------------------------------------


def test_percentile_uses_linear_interpolation():
    values = [10.0, 20.0, 30.0, 40.0]

    assert percentile(values, 50) == pytest.approx(25.0)
    assert percentile(values, 95) == pytest.approx(38.5)
    assert percentile(values, 0) == pytest.approx(10.0)
    assert percentile(values, 100) == pytest.approx(40.0)
    assert percentile([7.5], 95) == pytest.approx(7.5)
    assert percentile([], 50) == 0.0


def test_summarize_latency_reports_schema_fields():
    latency = summarize_latency([100.0, 200.0, 300.0, 400.0], n_errors=1)

    assert set(latency) == {"p50_ms", "p95_ms", "mean_ms", "total_s", "n_errors"}
    assert latency["p50_ms"] == pytest.approx(250.0)
    assert latency["mean_ms"] == pytest.approx(250.0)
    assert latency["total_s"] == pytest.approx(1.0)
    assert latency["n_errors"] == 1
    assert summarize_latency([], n_errors=0)["p50_ms"] == 0.0


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


def test_official_pricing_constants_match_the_documented_source():
    assert PRICING_SOURCE_URL.endswith("/zh-cn/quick_start/pricing")
    flash = CNY_PER_MILLION["deepseek-flash"]
    assert flash["input_cache_miss"]["off_peak"] == 1.0
    assert flash["input_cache_miss"]["peak"] == 2.0
    assert flash["output"]["off_peak"] == 4.0
    assert flash["output"]["peak"] == 8.0


def test_cost_estimation_uses_peak_and_off_peak_rates():
    off_peak_moment = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)  # 北京 21:00
    peak_moment = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)  # 北京 10:00 周一
    assert is_peak(off_peak_moment) is False
    assert is_peak(peak_moment) is True
    assert pricing_band(off_peak_moment).band == "off_peak"
    assert pricing_band(peak_moment).band == "peak"

    cost = estimate_cost(1_000_000, 1_000_000, model="deepseek-flash", run_time=off_peak_moment)
    # 1 元输入 + 4 元输出
    assert cost["estimated_cny"] == pytest.approx(5.0)
    assert cost["total_tokens"] == 2_000_000
    assert "缓存未命中" in cost["pricing_note"]
    assert PRICING_SOURCE_URL in cost["pricing_note"]

    peak_cost = estimate_cost(1_000_000, 1_000_000, model="deepseek-flash", run_time=peak_moment)
    assert peak_cost["estimated_cny"] == pytest.approx(10.0)


def test_cost_falls_back_for_unknown_model_and_supports_cache_hit():
    cost = estimate_cost(1_000_000, 0, model="deepseek-chat", run_time="2026-11-02T13:00:00+08:00")

    assert cost["estimated_cny"] == pytest.approx(1.0)
    assert "回退" in cost["pricing_note"]

    cached = estimate_cost(
        1_000_000, 0, model="deepseek-flash", run_time="2026-11-02T13:00:00+08:00", assume_cache_hit=True
    )
    assert cached["estimated_cny"] == pytest.approx(0.02)
    assert "缓存命中" in cached["pricing_note"]


def test_batch_cost_scales_linearly_to_100_items():
    cost = estimate_batch_cost(
        prompt_tokens=300 * 80,
        completion_tokens=100 * 80,
        n_samples=80,
        batch_size=100,
        model="deepseek-flash",
        run_time="2026-11-02T13:00:00+08:00",
    )

    assert cost["prompt_tokens"] == 30_000
    assert cost["completion_tokens"] == 10_000
    assert cost["estimated_cny"] > 0


# ---------------------------------------------------------------------------
# attribution
# ---------------------------------------------------------------------------


def _dataset_row(eval_id, text, golden):
    return {"eval_id": eval_id, "feedback_text": text, "golden_category": golden}


def test_category_terms_hit_detects_multi_intent_text():
    hits = category_terms_hit("快递一直没到，申请退款也没人处理")
    assert "物流" in hits
    assert "退换货" in hits


def test_build_badcases_covers_every_category_error_with_a_layer():
    rows = [
        _dataset_row("e1", "快递三天没到", "物流"),
        _dataset_row("e2", "信用卡付款失败", "支付"),
        _dataset_row("e3", "收到耳机破损", "商品质量"),
    ]
    predictions = {
        "e1": {"predicted_category": "物流", "confidence": 0.8},
        "e2": {"predicted_category": "退换货", "confidence": 0.5},
        "e3": {"predicted_category": "待确认", "confidence": 0.5},
    }

    cases = build_badcases(rows, predictions, mode="deepseek")

    assert [case["eval_id"] for case in cases] == ["e2", "e3"]
    assert all(case["layer"] in LAYERS for case in cases)
    assert all(case["reason"] and case["proposed_fix"] for case in cases)
    counts = count_layers(cases)
    assert set(counts) == set(LAYERS)
    assert sum(counts.values()) == 2


def test_overrides_replace_heuristic_attribution():
    rows = [_dataset_row("e1", "快递三天没到", "物流")]
    predictions = {"e1": {"predicted_category": "支付", "confidence": 0.9}}

    cases = build_badcases(
        rows,
        predictions,
        mode="deepseek",
        overrides={"e1": {"layer": "数据", "reason": "golden 有歧义", "proposed_fix": "复核标注"}},
    )

    assert cases[0]["layer"] == "数据"
    assert cases[0]["reason"] == "golden 有歧义"
    assert cases[0]["proposed_fix"] == "复核标注"
    with pytest.raises(ValueError, match="layer"):
        build_badcases(rows, predictions, mode="deepseek", overrides={"e1": {"layer": "随便"}})


def test_rule_mode_attributes_keyword_errors_to_rules_layer():
    rows = [_dataset_row("e1", "物流客服", "客服")]
    predictions = {"e1": {"predicted_category": "待确认", "confidence": 0.4}}

    cases = build_badcases(rows, predictions, mode="rule")

    assert cases[0]["layer"] == "规则"


# ---------------------------------------------------------------------------
# scripts/run_eval.py
# ---------------------------------------------------------------------------


def _load_run_eval():
    module_path = PROJECT_ROOT / "scripts" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("voiceboard_run_eval", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run_eval_module():
    return _load_run_eval()


def _write_dataset(path: Path, rows):
    import csv

    columns = [
        "eval_id",
        "feedback_text",
        "country",
        "user_type",
        "product_category",
        "rating",
        "created_at",
        "golden_category",
        "golden_impact_level",
        "source",
        "source_ref",
        "label_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def test_load_dataset_validates_and_orders_rows(run_eval_module, tmp_path):
    dataset = tmp_path / "eval.csv"
    _write_dataset(
        dataset,
        [
            {
                "eval_id": "v1-001",
                "feedback_text": "快递没到",
                "golden_category": "物流",
                "golden_impact_level": "4",
                "rating": "2",
            },
            {
                "eval_id": "v1-002",
                "feedback_text": "退款失败",
                "golden_category": "退换货",
                "golden_impact_level": "5",
                "rating": "1",
            },
        ],
    )

    rows = run_eval_module.load_dataset(dataset)

    assert [row["eval_id"] for row in rows] == ["v1-001", "v1-002"]
    assert rows[0]["golden_impact_level"] == 4
    assert rows[1]["rating"] == 1
    assert len(run_eval_module.load_dataset(dataset, limit=1)) == 1


def test_load_dataset_rejects_missing_columns_bad_labels_and_duplicates(run_eval_module, tmp_path):
    dataset = tmp_path / "eval.csv"
    dataset.write_text("eval_id,feedback_text\n1,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少必需列"):
        run_eval_module.load_dataset(dataset)

    _write_dataset(
        dataset,
        [{"eval_id": "1", "feedback_text": "x", "golden_category": "广告"}],
    )
    with pytest.raises(ValueError, match="golden_category"):
        run_eval_module.load_dataset(dataset)

    _write_dataset(
        dataset,
        [
            {"eval_id": "1", "feedback_text": "x", "golden_category": "物流"},
            {"eval_id": "1", "feedback_text": "y", "golden_category": "支付"},
        ],
    )
    with pytest.raises(ValueError, match="重复"):
        run_eval_module.load_dataset(dataset)


def test_rule_evaluation_assembles_full_result_schema(run_eval_module, tmp_path):
    dataset = tmp_path / "eval.csv"
    _write_dataset(
        dataset,
        [
            {"eval_id": "1", "feedback_text": "包裹配送三天没到", "golden_category": "物流", "golden_impact_level": "4", "rating": "2"},
            {"eval_id": "2", "feedback_text": "信用卡付款失败", "golden_category": "支付", "golden_impact_level": "5", "rating": "1"},
            {"eval_id": "3", "feedback_text": "客服两天没回复", "golden_category": "客服", "golden_impact_level": "3", "rating": "3"},
        ],
    )
    out = tmp_path / "rule.json"
    predictions_out = tmp_path / "predictions.csv"
    badcases_out = tmp_path / "badcases.csv"

    code = run_eval_module.main(
        [
            "--mode",
            "rule",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
            "--predictions-out",
            str(predictions_out),
            "--badcases-out",
            str(badcases_out),
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {
        "run_id",
        "mode",
        "model",
        "prompt_version",
        "dataset",
        "n",
        "timestamp",
        "metrics",
        "cost",
        "latency",
        "failures",
    }
    assert payload["mode"] == "rule"
    assert payload["n"] == 3
    assert payload["failures"] == []
    assert payload["cost"]["estimated_cny"] == 0.0
    assert set(payload["metrics"]) >= {
        "accuracy_business",
        "accuracy_e2e",
        "macro_recall_business",
        "key_class_recall",
        "per_class",
        "confusion_matrix",
        "uncertain_count",
        "uncertain_rate",
        "business_to_uncertain_rate",
        "uncertain_to_business_rate",
        "human_revision_rate_estimate",
        "impact_mae",
        "impact_exact_rate",
    }
    assert set(payload["latency"]) == {"p50_ms", "p95_ms", "mean_ms", "total_s", "n_errors"}
    assert predictions_out.exists() and badcases_out.exists()
    prediction_rows = list(
        __import__("csv").DictReader(predictions_out.read_text(encoding="utf-8").splitlines())
    )
    assert len(prediction_rows) == 3
    assert set(prediction_rows[0]) >= {
        "eval_id",
        "predicted_category",
        "predicted_impact",
        "confidence",
        "reason",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "error",
    }


class _FakeDeepSeekClassifier:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def classify_with_meta(self, record):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_deepseek_retry_then_abort_writes_failures_and_no_official_result(run_eval_module, tmp_path, monkeypatch):
    dataset = tmp_path / "eval.csv"
    _write_dataset(
        dataset,
        [
            {"eval_id": "1", "feedback_text": "快递没到", "golden_category": "物流", "golden_impact_level": "4", "rating": "2"},
            {"eval_id": "2", "feedback_text": "付款失败", "golden_category": "支付", "golden_impact_level": "5", "rating": "1"},
        ],
    )
    classifier = _FakeDeepSeekClassifier(
        [
            (run_eval_module.ClassificationResult("物流", 4, 0.8, "命中", "deepseek"), {"latency_ms": 100.0, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
            RuntimeError("boom-1"),
            RuntimeError("boom-2"),
        ]
    )
    monkeypatch.setattr(run_eval_module, "DeepSeekClassifier", lambda **kwargs: classifier)
    monkeypatch.setattr(run_eval_module, "resolve_api_key", lambda env_name, env_file: "test-key")

    out = tmp_path / "deepseek.json"
    code = run_eval_module.main(
        [
            "--mode",
            "deepseek",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
            "--failures-out",
            str(tmp_path / "failures.json"),
        ]
    )

    assert code == 2
    assert not out.exists()  # 失败整批不产出正式结果
    failures = json.loads((tmp_path / "failures.json").read_text(encoding="utf-8"))
    assert failures["failed_eval_id"] == "2"
    assert failures["failures"][0]["error"].startswith("RuntimeError")
    assert len(failures["partial_predictions"]) == 1
    assert classifier.calls == 3  # 第 1 条成功 + 第 2 条重试 2 次


def test_deepseek_success_path_writes_json_predictions_and_cost(run_eval_module, tmp_path, monkeypatch):
    dataset = tmp_path / "eval.csv"
    _write_dataset(
        dataset,
        [
            {"eval_id": "1", "feedback_text": "快递没到", "golden_category": "物流", "golden_impact_level": "4", "rating": "2"},
            {"eval_id": "2", "feedback_text": "付款失败", "golden_category": "支付", "golden_impact_level": "5", "rating": "1"},
        ],
    )

    class _SuccessClassifier:
        def __init__(self):
            self.calls = 0

        def classify_with_meta(self, record):
            self.calls += 1
            category = "物流" if "快递" in record["feedback_text"] else "支付"
            result = run_eval_module.ClassificationResult(category, 4, 0.9, "命中", "deepseek")
            return result, {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "latency_ms": 800.0}

    classifier = _SuccessClassifier()
    monkeypatch.setattr(run_eval_module, "DeepSeekClassifier", lambda **kwargs: classifier)
    monkeypatch.setattr(run_eval_module, "resolve_api_key", lambda env_name, env_file: "test-key")

    out = tmp_path / "deepseek.json"
    predictions_out = tmp_path / "predictions.csv"
    badcases_out = tmp_path / "badcases.csv"
    code = run_eval_module.main(
        [
            "--mode",
            "deepseek",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
            "--predictions-out",
            str(predictions_out),
            "--badcases-out",
            str(badcases_out),
            "--model",
            "deepseek-flash",
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["mode"] == "deepseek"
    assert payload["model"] == "deepseek-flash"
    assert payload["prompt_version"] == "deepseek-classify-v2"
    assert payload["failures"] == []
    assert payload["metrics"]["accuracy_e2e"] == 1.0
    assert payload["metrics"]["accuracy_business"] == 1.0
    assert payload["cost"]["prompt_tokens"] == 200
    assert payload["cost"]["completion_tokens"] == 40
    assert payload["cost"]["estimated_cny"] > 0
    assert "官方价目表" in payload["cost"]["pricing_note"]
    assert payload["latency"]["p50_ms"] == pytest.approx(800.0)
    assert classifier.calls == 2


def test_replay_applies_attribution_overrides(run_eval_module, tmp_path):
    dataset = tmp_path / "eval.csv"
    _write_dataset(
        dataset,
        [
            {"eval_id": "1", "feedback_text": "快递没到", "golden_category": "物流", "golden_impact_level": "4", "rating": "2"},
        ],
    )
    predictions_in = tmp_path / "predictions_deepseek_v1.csv"
    predictions_in.write_text(
        "eval_id,predicted_category,predicted_impact,confidence,reason,latency_ms,prompt_tokens,completion_tokens,error\n"
        "1,支付,4,0.9,误判,120,10,5,\n",
        encoding="utf-8",
    )
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "1": {
                    "layer": "数据",
                    "reason": "该条 golden 需复核",
                    "proposed_fix": "补充规则与复核标注",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    badcases_out = tmp_path / "badcases.csv"

    code = run_eval_module.main(
        [
            "--mode",
            "replay",
            "--dataset",
            str(dataset),
            "--predictions-in",
            str(predictions_in),
            "--out",
            str(tmp_path / "replay.json"),
            "--badcases-out",
            str(badcases_out),
            "--attribution-overrides",
            str(overrides_path),
        ]
    )

    assert code == 0
    badcases = list(
        __import__("csv").DictReader(badcases_out.read_text(encoding="utf-8").splitlines())
    )
    assert badcases[0]["layer"] == "数据"
    assert badcases[0]["reason"] == "该条 golden 需复核"
    assert badcases[0]["proposed_fix"] == "补充规则与复核标注"


def test_read_dotenv_parses_values_without_exposing_them(run_eval_module, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nDEEPSEEK_API_KEY=sk-test-value\nDEEPSEEK_MODEL='deepseek-flash'\nUNRELATED=1\n",
        encoding="utf-8",
    )

    values = run_eval_module.read_dotenv(
        env_file, ["DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"]
    )

    assert values == {"DEEPSEEK_API_KEY": "sk-test-value", "DEEPSEEK_MODEL": "deepseek-flash"}
    assert run_eval_module.read_dotenv(tmp_path / "missing.env", ["DEEPSEEK_API_KEY"]) == {}


def test_resolve_model_prefers_explicit_then_env_then_default(run_eval_module, tmp_path):
    dotenv = {"DEEPSEEK_MODEL": "deepseek-flash"}

    assert run_eval_module._resolve_model("deepseek", "deepseek-v4-pro", dotenv) == "deepseek-v4-pro"
    assert run_eval_module._resolve_model("deepseek", None, dotenv) == "deepseek-flash"
    assert run_eval_module._resolve_model("rule", "deepseek-v4-pro", dotenv) == "rule-keyword-v1"


def test_replay_recomputes_metrics_from_predictions(run_eval_module, tmp_path):
    dataset = tmp_path / "eval.csv"
    _write_dataset(
        dataset,
        [
            {"eval_id": "1", "feedback_text": "快递没到", "golden_category": "物流", "golden_impact_level": "4", "rating": "2"},
            {"eval_id": "2", "feedback_text": "付款失败", "golden_category": "支付", "golden_impact_level": "5", "rating": "1"},
        ],
    )
    predictions_in = tmp_path / "predictions.csv"
    predictions_in.write_text(
        "eval_id,predicted_category,predicted_impact,confidence,reason,latency_ms,prompt_tokens,completion_tokens,error\n"
        "1,物流,4,0.9,命中,120,10,5,\n"
        "2,物流,4,0.7,误判,150,10,5,\n",
        encoding="utf-8",
    )
    out = tmp_path / "replay.json"

    code = run_eval_module.main(
        [
            "--mode",
            "replay",
            "--dataset",
            str(dataset),
            "--predictions-in",
            str(predictions_in),
            "--out",
            str(out),
            "--badcases-out",
            str(tmp_path / "badcases.csv"),
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["mode"] == "replay"
    assert payload["n"] == 2
    assert payload["metrics"]["accuracy_e2e"] == pytest.approx(0.5)
    assert payload["cost"]["prompt_tokens"] == 20
    assert payload["cost"]["completion_tokens"] == 10
    assert payload["latency"]["p50_ms"] == pytest.approx(135.0)
    badcases = list(
        __import__("csv").DictReader(
            (tmp_path / "badcases.csv").read_text(encoding="utf-8").splitlines()
        )
    )
    assert [row["eval_id"] for row in badcases] == ["2"]
    assert badcases[0]["layer"] in LAYERS
