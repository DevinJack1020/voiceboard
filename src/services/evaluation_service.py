"""评测结果读取与运行时人工修订统计。

服务层只做只读聚合：不依赖 Streamlit，也不写入任何数据。

两类数据来源：

1. 离线评测产物（由 ``scripts/run_eval.py`` 生成，schema 见任务约定）：
   - ``evals/results/deepseek_v1.json``，缺失时回退 ``evals/results/rule_v1.json``；
   - ``evals/results/badcases_v1.csv``。
   文件缺失、字段缺失或 JSON 损坏时返回 ``None`` / 空列表，由页面显示真实空状态，
   绝不补造数字。目录可用环境变量 ``VOICEBOARD_EVAL_DIR`` 覆盖（仅测试用）。

2. 运行时 SQLite 反馈与修订审计：
   - 已分类反馈 = ``classification_source`` ∈ {rule, deepseek, manual}
     （表 CHECK 约束保证）；
   - 待确认 = ``category = '待确认'``，它是分类结果而不是分类来源，
     因此仍计入“已分类反馈”分母；
   - 人工修订条数 = ``feedback_revisions`` 行数；
   - 人工修订率 = 有修订记录的 distinct feedback 数 / 已分类反馈数。
     同一条反馈多次修订只计 1 条（按反馈去重），修订行数单独展示。
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.db import connect
from src.repository import VoiceBoardRepository


RESULTS_DIR = PROJECT_ROOT / "evals" / "results"
RESULT_FILENAMES = ("deepseek_v1.json", "rule_v1.json")
BADCASES_FILENAME = "badcases_v1.csv"
BADCASE_LAYERS = ("数据", "提示词", "规则", "交互")
CLASSIFIED_SOURCES = ("rule", "deepseek", "manual")
UNCERTAIN_CATEGORY = "待确认"
DASH = "—"


def evaluation_results_dir() -> Path:
    """返回评测结果目录；测试可用 ``VOICEBOARD_EVAL_DIR`` 指向临时 fixture。"""
    configured = os.getenv("VOICEBOARD_EVAL_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return RESULTS_DIR


# ---------------------------------------------------------------------------
# 轻量容错取值：评测 JSON 来自外部脚本，字段可能缺失或类型不对
# ---------------------------------------------------------------------------


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: object) -> int | None:
    number = _as_float(value)
    return None if number is None else int(number)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, str):
        return ""
    return str(value).strip()


def _as_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _as_mapping_list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (list, tuple)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator > 0 else 0.0


# ---------------------------------------------------------------------------
# 离线评测结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationResult:
    """一次离线评测结果（字段容错，缺失时为 0 / 空字符串）。"""

    source_path: Path
    run_id: str
    mode: str
    model: str
    prompt_version: str
    dataset: str
    n: int
    timestamp: str
    metrics: Mapping[str, Any]
    cost: Mapping[str, Any]
    latency: Mapping[str, Any]
    failures: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _as_mapping(self.raw))

    @property
    def label(self) -> str:
        if self.mode == "deepseek" or "deepseek" in self.model.lower():
            name = "DeepSeek 真实评测"
        elif self.mode == "rule":
            name = "规则基线"
        else:
            name = "离线评测"
        return f"{name}（{self.source_path.name}）"

    @property
    def dataset_size(self) -> int:
        if self.n > 0:
            return self.n
        support = sum(
            values["support"] or 0 for values in self.per_class.values()
        )
        return int(support)

    @property
    def per_class(self) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for category, values in _as_mapping(self.metrics.get("per_class")).items():
            category = category.strip()
            if not category or not isinstance(values, Mapping):
                continue
            raw = _as_mapping(values)
            normalized[category] = {
                "precision": _as_float(raw.get("precision")),
                "recall": _as_float(raw.get("recall")),
                "f1": _as_float(raw.get("f1")),
                "support": _as_int(raw.get("support")) or 0,
            }
        return normalized

    @property
    def confusion_matrix(self) -> dict[str, dict[str, int]]:
        normalized: dict[str, dict[str, int]] = {}
        for golden, row in _as_mapping(self.metrics.get("confusion_matrix")).items():
            golden = golden.strip()
            if not golden or not isinstance(row, Mapping):
                continue
            counts = {
                predicted.strip(): _as_int(count) or 0
                for predicted, count in _as_mapping(row).items()
                if predicted.strip()
            }
            normalized[golden] = counts
        return normalized

    @property
    def key_class_recall(self) -> dict[str, float | None]:
        return {
            category.strip(): _as_float(value)
            for category, value in _as_mapping(
                self.metrics.get("key_class_recall")
            ).items()
            if category.strip()
        }

    def metric_number(self, key: str) -> float | None:
        return _as_float(self.metrics.get(key))

    def cost_number(self, key: str) -> float | None:
        return _as_float(self.cost.get(key))

    def latency_number(self, key: str) -> float | None:
        return _as_float(self.latency.get(key))

    @property
    def pricing_note(self) -> str:
        return _as_text(self.cost.get("pricing_note"))


def build_evaluation_result(
    source_path: Path | str, payload: Mapping[str, Any]
) -> EvaluationResult:
    """把原始 JSON dict 归一化成 :class:`EvaluationResult`（不抛异常）。"""
    payload = _as_mapping(payload)
    n_value = _as_int(payload.get("n")) or 0
    return EvaluationResult(
        source_path=Path(source_path),
        run_id=_as_text(payload.get("run_id")),
        mode=_as_text(payload.get("mode")),
        model=_as_text(payload.get("model")),
        prompt_version=_as_text(payload.get("prompt_version")),
        dataset=_as_text(payload.get("dataset")),
        n=max(0, n_value),
        timestamp=_as_text(payload.get("timestamp")),
        metrics=_as_mapping(payload.get("metrics")),
        cost=_as_mapping(payload.get("cost")),
        latency=_as_mapping(payload.get("latency")),
        failures=tuple(_as_mapping_list(payload.get("failures"))),
        raw=payload,
    )


def load_result_file(path: Path | str) -> EvaluationResult | None:
    """读取单个结果 JSON；不存在、不可读、JSON 损坏或结构不对时返回 None。"""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return build_evaluation_result(target, payload)


def available_result_files(
    results_dir: Path | str | None = None,
) -> list[Path]:
    """按优先级列出存在的候选结果文件（deepseek_v1 在前，rule_v1 兜底）。"""
    directory = Path(results_dir) if results_dir is not None else evaluation_results_dir()
    return [directory / name for name in RESULT_FILENAMES if (directory / name).is_file()]


def load_evaluation_results(
    results_dir: Path | str | None = None,
) -> list[EvaluationResult]:
    """读取全部可用的评测结果，供页面切换展示；全部缺失时返回空列表。"""
    results: list[EvaluationResult] = []
    for path in available_result_files(results_dir):
        result = load_result_file(path)
        if result is not None:
            results.append(result)
    return results


def load_evaluation_result(
    results_dir: Path | str | None = None,
) -> EvaluationResult | None:
    """返回首选结果：deepseek_v1.json，缺失/损坏时回退 rule_v1.json。"""
    results = load_evaluation_results(results_dir)
    return results[0] if results else None


# ---------------------------------------------------------------------------
# Badcase 归因
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Badcase:
    eval_id: str
    feedback_text: str
    golden_category: str
    predicted_category: str
    confidence: float | None
    layer: str
    reason: str
    proposed_fix: str

    @property
    def layer_label(self) -> str:
        return self.layer or "未归因"


def load_badcases(path: Path | str | None = None) -> list[Badcase]:
    """读取 badcases CSV；文件缺失、为空或列缺失时返回空列表，不抛异常。"""
    if path is None:
        target = evaluation_results_dir() / BADCASES_FILENAME
    else:
        target = Path(path)
    try:
        text = target.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    cases: list[Badcase] = []
    for row in reader:
        if not isinstance(row, Mapping):
            continue
        cases.append(
            Badcase(
                eval_id=_as_text(row.get("eval_id")),
                feedback_text=_as_text(row.get("feedback_text")),
                golden_category=_as_text(row.get("golden_category")),
                predicted_category=_as_text(row.get("predicted_category")),
                confidence=_as_float(row.get("confidence")),
                layer=_as_text(row.get("layer")),
                reason=_as_text(row.get("reason")),
                proposed_fix=_as_text(row.get("proposed_fix")),
            )
        )
    return cases


def filter_badcases(
    cases: Sequence[Badcase], layer: str | None
) -> list[Badcase]:
    """按归因层级筛选；``None`` / 空串 / “全部” 返回全部。"""
    if not layer or layer == "全部":
        return list(cases)
    return [case for case in cases if case.layer == layer]


def badcase_layer_counts(cases: Sequence[Badcase]) -> dict[str, int]:
    """统计四个约定归因层级的条数（未知层级不计入）。"""
    counts = {layer: 0 for layer in BADCASE_LAYERS}
    for case in cases:
        if case.layer in counts:
            counts[case.layer] += 1
    return counts


# ---------------------------------------------------------------------------
# 运行时人工修订统计（SQLite，全部参数化）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRevisionStat:
    source: str
    total: int
    revised: int
    revision_rate: float


@dataclass(frozen=True)
class ProductCategoryUncertainStat:
    product_category: str
    total: int
    uncertain: int
    uncertain_rate: float


@dataclass(frozen=True)
class CategoryShare:
    category: str
    count: int
    share: float


@dataclass(frozen=True)
class RevisionStatistics:
    """运行时反馈与人工修订统计；空库或表缺失时全部为 0。"""

    total_feedback: int = 0
    classified_count: int = 0
    uncertain_count: int = 0
    uncertain_rate: float = 0.0
    revision_count: int = 0
    revised_feedback_count: int = 0
    human_revision_rate: float = 0.0
    by_source: tuple[SourceRevisionStat, ...] = ()
    uncertain_by_product_category: tuple[ProductCategoryUncertainStat, ...] = ()
    category_shares: tuple[CategoryShare, ...] = ()


def _resolve_database(
    source: VoiceBoardRepository | Path | str,
) -> Path:
    database = getattr(source, "database", None)
    if database is not None:
        return Path(database)
    return Path(source)


def collect_revision_statistics(
    source: VoiceBoardRepository | Path | str,
) -> RevisionStatistics:
    """计算运行时人工修订统计。

    ``source`` 可以是 :class:`VoiceBoardRepository`、数据库路径字符串或 Path。
    空库、表未建或数据库文件不可读时返回全 0 统计，不抛异常。
    """
    database = _resolve_database(source)
    try:
        with connect(database) as connection:
            return _collect_statistics(connection)
    except sqlite3.OperationalError:
        return RevisionStatistics()


def _collect_statistics(connection: sqlite3.Connection) -> RevisionStatistics:
    total = int(connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0])
    uncertain = int(
        connection.execute(
            "SELECT COUNT(*) FROM feedback WHERE category = ?",
            (UNCERTAIN_CATEGORY,),
        ).fetchone()[0]
    )
    source_totals = {
        _as_text(row["classification_source"]): int(row["total"])
        for row in connection.execute(
            """
            SELECT classification_source, COUNT(*) AS total
            FROM feedback
            GROUP BY classification_source
            """
        )
    }
    revised_by_source = {
        _as_text(row["classification_source"]): int(row["revised"])
        for row in connection.execute(
            """
            SELECT f.classification_source AS classification_source,
                   COUNT(DISTINCT r.feedback_id) AS revised
            FROM feedback_revisions AS r
            JOIN feedback AS f ON f.id = r.feedback_id
            WHERE f.classification_source IN (?, ?, ?)
            GROUP BY f.classification_source
            """,
            CLASSIFIED_SOURCES,
        )
    }

    classified_count = sum(
        source_totals.get(source, 0) for source in CLASSIFIED_SOURCES
    )
    for source_name in source_totals:
        if source_name not in CLASSIFIED_SOURCES:
            classified_count += source_totals[source_name]
    ordered_sources = list(CLASSIFIED_SOURCES)
    ordered_sources.extend(
        source_name
        for source_name in source_totals
        if source_name not in CLASSIFIED_SOURCES
    )
    by_source = tuple(
        SourceRevisionStat(
            source=source_name,
            total=source_totals.get(source_name, 0),
            revised=revised_by_source.get(source_name, 0),
            revision_rate=_rate(
                revised_by_source.get(source_name, 0),
                source_totals.get(source_name, 0),
            ),
        )
        for source_name in ordered_sources
    )

    revision_count = int(
        connection.execute("SELECT COUNT(*) FROM feedback_revisions").fetchone()[0]
    )
    revised_feedback_count = int(
        connection.execute(
            """
            SELECT COUNT(DISTINCT r.feedback_id) AS revised
            FROM feedback_revisions AS r
            JOIN feedback AS f ON f.id = r.feedback_id
            WHERE f.classification_source IN (?, ?, ?)
            """,
            CLASSIFIED_SOURCES,
        ).fetchone()[0]
    )

    uncertain_by_product_category = tuple(
        ProductCategoryUncertainStat(
            product_category=_as_text(row["product_category"]),
            total=int(row["total"]),
            uncertain=int(row["uncertain"]),
            uncertain_rate=_rate(int(row["uncertain"]), int(row["total"])),
        )
        for row in connection.execute(
            """
            SELECT product_category,
                   COUNT(*) AS total,
                   SUM(CASE WHEN category = ? THEN 1 ELSE 0 END) AS uncertain
            FROM feedback
            GROUP BY product_category
            ORDER BY total DESC, product_category
            """,
            (UNCERTAIN_CATEGORY,),
        )
    )

    category_shares = tuple(
        CategoryShare(
            category=_as_text(row["category"]),
            count=int(row["count"]),
            share=_rate(int(row["count"]), total),
        )
        for row in connection.execute(
            """
            SELECT category, COUNT(*) AS count
            FROM feedback
            GROUP BY category
            ORDER BY count DESC, category
            """
        )
    )

    return RevisionStatistics(
        total_feedback=total,
        classified_count=classified_count,
        uncertain_count=uncertain,
        uncertain_rate=_rate(uncertain, classified_count),
        revision_count=revision_count,
        revised_feedback_count=revised_feedback_count,
        human_revision_rate=_rate(revised_feedback_count, classified_count),
        by_source=by_source,
        uncertain_by_product_category=uncertain_by_product_category,
        category_shares=category_shares,
    )


# ---------------------------------------------------------------------------
# 展示格式化（纯函数，页面复用）
# ---------------------------------------------------------------------------


def format_percent(value: object, digits: int = 1) -> str:
    number = _as_float(value)
    return DASH if number is None else f"{number * 100:.{digits}f}%"


def format_decimal(value: object, digits: int = 2) -> str:
    number = _as_float(value)
    return DASH if number is None else f"{number:.{digits}f}"


def format_int(value: object) -> str:
    number = _as_int(value)
    return DASH if number is None else f"{number:,}"


def format_ms(value: object) -> str:
    number = _as_float(value)
    return DASH if number is None else f"{number:,.0f} ms"


def format_tokens(value: object) -> str:
    number = _as_int(value)
    return DASH if number is None else f"{number:,}"


def format_cny(value: object) -> str:
    number = _as_float(value)
    if number is None:
        return DASH
    if abs(number) < 1:
        return f"¥{number:.4f}"
    return f"¥{number:,.2f}"


# ---------------------------------------------------------------------------
# 服务门面
# ---------------------------------------------------------------------------


class EvaluationService:
    """页面入口：组合离线评测产物与运行时 SQLite 统计。"""

    def __init__(
        self,
        repository: VoiceBoardRepository,
        results_dir: Path | str | None = None,
    ):
        self.repository = repository
        self.results_dir = Path(results_dir) if results_dir is not None else None

    def _directory(self) -> Path:
        if self.results_dir is not None:
            return self.results_dir
        return evaluation_results_dir()

    def load_results(self) -> list[EvaluationResult]:
        return load_evaluation_results(self._directory())

    def load_result(self) -> EvaluationResult | None:
        result = load_evaluation_result(self._directory())
        return result

    def load_badcases(self) -> list[Badcase]:
        return load_badcases(self._directory() / BADCASES_FILENAME)

    def revision_statistics(self) -> RevisionStatistics:
        return collect_revision_statistics(self.repository)
