"""纯函数评测指标。

口径与 ``evals/results/*.json`` 的 ``metrics`` 字段一一对应，均为可复算的确定性函数：

- ``accuracy_e2e``：全部样本的 exact match（含 ``待确认``）。
- ``accuracy_business``：仅在 golden 属于 6 个业务类的样本上计算准确率，
  预测必须与 golden 完全一致才算正确。
- ``macro_recall_business``：6 个业务类 recall 的宏平均，只统计 support>0 的类
  （无样本的类不参与平均，避免把零样本类当成 0 分拉低指标）。
- ``key_class_recall``：物流 / 支付 / 商品质量 三个关键类的 recall。
- ``per_class``：7 个类别（含 ``待确认``）的 precision / recall / f1 / support；
  分母为 0 时该分母对应的指标记 0.0（不抛异常），便于空集与小样本场景。
- ``confusion_matrix``：``golden -> predicted -> count``，固定输出完整 7×7
  （含 0），方便下游页面直接渲染。
- ``uncertain_*``：``待确认`` 相关比例。
  - ``uncertain_rate`` = 预测为 ``待确认`` 的样本 / n；
  - ``business_to_uncertain_rate`` = golden 为业务类但被预测为 ``待确认`` 的比例
    （业务类被降级/漏判）；
  - ``uncertain_to_business_rate`` = golden 为 ``待确认`` 却被强行归入业务类的
    比例（过度自信）；
  - ``human_revision_rate_estimate`` = (预测为 ``待确认`` 的样本数 +
    业务类误判数) / n，即"假设全部输出经人工复核、错误都被修订"时的修订率估计。
    真实线上修订率必须用 ``feedback_revisions`` 实测（见 evaluation_service），
    这里是离线代理指标，不是线上值。
- ``impact_mae`` / ``impact_exact_rate``：影响度（1-5）的平均绝对误差与完全
  一致率；任一侧缺失的样本跳过，空集时记 0.0。

所有标签必须属于 :data:`ALL_CATEGORIES`，否则抛 ``ValueError``（在数据加载阶段
尽早暴露脏标签，避免静默算错指标）。
"""

from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

BUSINESS_CATEGORIES = ("物流", "支付", "商品质量", "搜索推荐", "客服", "退换货")
UNCERTAIN = "待确认"
ALL_CATEGORIES = BUSINESS_CATEGORIES + (UNCERTAIN,)
KEY_CATEGORIES = ("物流", "支付", "商品质量")


def _validate_labels(labels: Sequence[str]) -> None:
    for label in labels:
        if label not in ALL_CATEGORIES:
            raise ValueError(f"未知类别：{label!r}，必须属于 {ALL_CATEGORIES}")


def _rate(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _paired(
    goldens: Sequence[str], predictions: Sequence[str]
) -> list[tuple[str, str]]:
    if len(goldens) != len(predictions):
        raise ValueError(
            f"golden 与 prediction 数量不一致：{len(goldens)} != {len(predictions)}"
        )
    _validate_labels(goldens)
    _validate_labels(predictions)
    return list(zip(goldens, predictions, strict=True))


def accuracy(goldens: Sequence[str], predictions: Sequence[str]) -> float:
    """端到端 exact match 准确率（含 ``待确认``）。"""
    pairs = _paired(goldens, predictions)
    return _rate(sum(g == p for g, p in pairs), len(pairs))


def accuracy_business(goldens: Sequence[str], predictions: Sequence[str]) -> float:
    """仅 golden 为 6 个业务类的样本上的准确率。"""
    pairs = [(g, p) for g, p in _paired(goldens, predictions) if g != UNCERTAIN]
    return _rate(sum(g == p for g, p in pairs), len(pairs))


def per_class_metrics(
    goldens: Sequence[str],
    predictions: Sequence[str],
    labels: Sequence[str] = ALL_CATEGORIES,
) -> dict[str, dict[str, float | int]]:
    """7 类别的 precision / recall / f1 / support（除零记 0.0）。"""
    pairs = _paired(goldens, predictions)
    metrics: dict[str, dict[str, float | int]] = {}
    for label in labels:
        if label not in ALL_CATEGORIES:
            raise ValueError(f"未知类别：{label!r}")
        true_positive = sum(g == label and p == label for g, p in pairs)
        predicted_positive = sum(p == label for _, p in pairs)
        support = sum(g == label for g, _ in pairs)
        precision = _rate(true_positive, predicted_positive)
        recall = _rate(true_positive, support)
        f1 = _rate(2 * precision * recall, precision + recall)
        metrics[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
    return metrics


def macro_recall_business(
    goldens: Sequence[str], predictions: Sequence[str]
) -> float:
    """6 个业务类 recall 的宏平均（只平均 support>0 的类）。"""
    per_class = per_class_metrics(goldens, predictions)
    recalls = [
        float(per_class[label]["recall"])
        for label in BUSINESS_CATEGORIES
        if int(per_class[label]["support"]) > 0
    ]
    return sum(recalls) / len(recalls) if recalls else 0.0


def key_class_recall(
    goldens: Sequence[str],
    predictions: Sequence[str],
    keys: Sequence[str] = KEY_CATEGORIES,
) -> dict[str, float]:
    """关键类（默认 物流/支付/商品质量）的 recall。"""
    per_class = per_class_metrics(goldens, predictions)
    return {label: float(per_class[label]["recall"]) for label in keys}


def confusion_matrix(
    goldens: Sequence[str],
    predictions: Sequence[str],
    labels: Sequence[str] = ALL_CATEGORIES,
) -> dict[str, dict[str, int]]:
    """``golden -> predicted -> count`` 的完整混淆矩阵（含 0 项）。"""
    pairs = _paired(goldens, predictions)
    counts = Counter(pairs)
    matrix: dict[str, dict[str, int]] = {}
    for golden in labels:
        matrix[golden] = {predicted: counts.get((golden, predicted), 0) for predicted in labels}
    return matrix


def uncertain_metrics(
    goldens: Sequence[str], predictions: Sequence[str]
) -> dict[str, float | int]:
    """待确认与人工修订率代理指标。"""
    pairs = _paired(goldens, predictions)
    total = len(pairs)
    uncertain_count = sum(p == UNCERTAIN for _, p in pairs)
    business_total = sum(g != UNCERTAIN for g, _ in pairs)
    business_to_uncertain = sum(
        g != UNCERTAIN and p == UNCERTAIN for g, p in pairs
    )
    uncertain_total = sum(g == UNCERTAIN for g, _ in pairs)
    uncertain_to_business = sum(
        g == UNCERTAIN and p != UNCERTAIN for g, p in pairs
    )
    business_errors = sum(
        g != UNCERTAIN and p != UNCERTAIN and g != p for g, p in pairs
    )
    return {
        "uncertain_count": uncertain_count,
        "uncertain_rate": _rate(uncertain_count, total),
        "business_to_uncertain_rate": _rate(business_to_uncertain, business_total),
        "uncertain_to_business_rate": _rate(uncertain_to_business, uncertain_total),
        # 全量人工复核假设下的修订率估计（离线代理指标，不是线上真实修订率）。
        "human_revision_rate_estimate": _rate(
            uncertain_count + business_errors, total
        ),
    }


def _impact_pairs(
    golden_impacts: Sequence[object] | None,
    predicted_impacts: Sequence[object] | None,
) -> list[tuple[int, int]]:
    if golden_impacts is None or predicted_impacts is None:
        return []
    if len(golden_impacts) != len(predicted_impacts):
        raise ValueError(
            "golden impact 与 predicted impact 数量不一致："
            f"{len(golden_impacts)} != {len(predicted_impacts)}"
        )
    pairs: list[tuple[int, int]] = []
    for golden, predicted in zip(golden_impacts, predicted_impacts, strict=True):
        if golden is None or predicted is None or golden == "" or predicted == "":
            continue
        pairs.append((int(golden), int(predicted)))
    return pairs


def impact_metrics(
    golden_impacts: Sequence[object] | None,
    predicted_impacts: Sequence[object] | None,
) -> dict[str, float]:
    """影响度 MAE 与完全一致率（缺失值跳过，空集记 0.0）。"""
    pairs = _impact_pairs(golden_impacts, predicted_impacts)
    if not pairs:
        return {"impact_mae": 0.0, "impact_exact_rate": 0.0}
    mae = sum(abs(g - p) for g, p in pairs) / len(pairs)
    exact = sum(g == p for g, p in pairs) / len(pairs)
    return {"impact_mae": float(mae), "impact_exact_rate": float(exact)}


def compute_metrics(
    goldens: Sequence[str],
    predictions: Sequence[str],
    golden_impacts: Sequence[object] | None = None,
    predicted_impacts: Sequence[object] | None = None,
) -> dict[str, object]:
    """按结果 JSON 的 ``metrics`` 字段顺序汇总全部指标。"""
    metrics: dict[str, object] = {
        "accuracy_business": accuracy_business(goldens, predictions),
        "accuracy_e2e": accuracy(goldens, predictions),
        "macro_recall_business": macro_recall_business(goldens, predictions),
        "key_class_recall": key_class_recall(goldens, predictions),
        "per_class": per_class_metrics(goldens, predictions),
        "confusion_matrix": confusion_matrix(goldens, predictions),
    }
    metrics.update(uncertain_metrics(goldens, predictions))
    metrics.update(impact_metrics(golden_impacts, predicted_impacts))
    return metrics


def summarize_labels(labels: Sequence[str]) -> Mapping[str, int]:
    """按类别计数（数据分布与错误分布都可用）。"""
    counts = Counter(labels)
    return {label: counts.get(label, 0) for label in ALL_CATEGORIES}
