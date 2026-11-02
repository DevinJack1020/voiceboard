"""VoiceBoard 离线分类评测引擎。

该包只包含纯函数与数据结构，不依赖 Streamlit / SQLite / 网络，
便于单元测试、复算（replay）与在其他脚本中复用。

对外导出的入口：

- :func:`src.evaluation.metrics.compute_metrics` 汇总评测指标（schema 与
  ``evals/results/*.json`` 的 ``metrics`` 字段一致）。
- :func:`src.evaluation.latency.summarize_latency` 汇总 p50/p95/均值/总耗时。
- :func:`src.evaluation.cost.estimate_cost` 按 DeepSeek 官方价估算 token 成本。
- :func:`src.evaluation.attribution.build_badcases` 为错例生成四层归因。
"""

from src.evaluation.attribution import (
    BAD_LAYER_RUBRIC,
    LAYERS,
    build_badcases,
    count_layers,
)
from src.evaluation.cost import (
    CNY_PER_MILLION,
    PRICING_FETCHED_AT,
    PRICING_SOURCE_URL,
    estimate_cost,
    pricing_band,
)
from src.evaluation.latency import percentile, summarize_latency
from src.evaluation.metrics import (
    ALL_CATEGORIES,
    BUSINESS_CATEGORIES,
    KEY_CATEGORIES,
    UNCERTAIN,
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

__all__ = [
    "ALL_CATEGORIES",
    "BAD_LAYER_RUBRIC",
    "BUSINESS_CATEGORIES",
    "CNY_PER_MILLION",
    "KEY_CATEGORIES",
    "LAYERS",
    "PRICING_FETCHED_AT",
    "PRICING_SOURCE_URL",
    "UNCERTAIN",
    "accuracy",
    "accuracy_business",
    "build_badcases",
    "compute_metrics",
    "confusion_matrix",
    "count_layers",
    "estimate_cost",
    "impact_metrics",
    "key_class_recall",
    "macro_recall_business",
    "per_class_metrics",
    "percentile",
    "pricing_band",
    "summarize_latency",
    "uncertain_metrics",
]
