"""``scripts/run_eval.py`` 的 CLI 契约与成本/延迟口径（docstring 同步发布）。

运行方式::

    # 规则基线（离线、无成本）
    python scripts/run_eval.py --mode rule --dataset evals/feedback_eval_v1.csv \
        --out <dir>/rule_v1.json --predictions-out <dir>/predictions_rule_v1.csv

    # DeepSeek 真实评测（需 voiceboard/.env 或环境变量 DEEPSEEK_API_KEY）
    python scripts/run_eval.py --mode deepseek --dataset evals/feedback_eval_v1.csv \
        --model deepseek-flash --out <dir>/deepseek_v1.json \
        --predictions-out <dir>/predictions_deepseek_v1.csv \
        --badcases-out <dir>/badcases_v1.csv

    # 复算：用已落盘的预测明细重新计算结果（不调用 API、不花钱）
    python scripts/run_eval.py --mode replay --dataset evals/feedback_eval_v1.csv \
        --predictions-in <dir>/predictions_deepseek_v1.csv \
        --out <dir>/deepseek_replay.json --badcases-out <dir>/badcases_v1.csv

CLI 参数
--------
``--dataset``           评测集 CSV（默认 ``evals/feedback_eval_v1.csv``）
``--mode``              ``rule`` | ``deepseek`` | ``replay``
``--out``               结果 JSON 路径
``--predictions-out``   预测明细 CSV 路径（rule/deepseek 产出）
``--predictions-in``    replay 模式的输入预测 CSV/JSONL
``--badcases-out``      Badcase CSV 路径（默认与 ``--out`` 同目录 ``badcases_v1.csv``）
``--attribution-overrides``  人工复核后的归因覆盖 JSON（eval_id -> layer/reason/proposed_fix）
``--limit``             只跑前 N 条（用于 3 条连通性验证）
``--model``             API 模型名（默认 DEEPSEEK_MODEL 环境变量，再回退分类器默认值）
``--api-key-env``       读取密钥的环境变量名（默认 ``DEEPSEEK_API_KEY``）
``--env-file``          .env 路径（默认项目根 ``.env``；只从文件读取，不打印密钥）
``--failures-out``      失败清单路径（默认 ``--out`` 加 ``.failures.json`` 后缀）

成本/延迟口径（写进结果 JSON，供文档引用）
------------------------------------------
- 单条耗时：一次 classify 的 wall-clock（毫秒）。DeepSeek 模式包含一次 HTTP
  往返；接口层自带 429/5xx/超时的 1 次重试，脚本层在失败后再重试 1 次，
  仍失败则**整批中止**、只写 failures、不写正式结果（与应用“失败不写入”一致）。
- 汇总口径：``p50_ms``/``p95_ms`` 为线性插值分位数，``mean_ms`` 为均值，
  ``total_s`` 为全部样本延时之和；失败样本不计入分位数，``n_errors`` 单独计数。
- token 口径：取自 API ``response.usage``（prompt/completion/total tokens），
  按条累加；缺失记 0。
- 成本口径：按 DeepSeek 官方价目表估算（见 ``src/evaluation/cost.py``：
  2026-11-02 抓取自 api-docs.deepseek.com，deepseek-flash 空闲时段
  输入缓存未命中 1 元/百万 tokens、输出 4 元/百万 tokens；高峰时段翻倍）。
  默认按“全部输入缓存未命中”的保守上限估算并注明；单批 100 条成本
  ≈ ``estimated_cny / n * 100``（线性外推，实际受文本长度分布影响）。
- 限流/并发：当前脚本**串行**逐条调用（80 条约 2-4 分钟），不并发；
  DeepSeek 官方并发上限很高（flash 2500），应用侧仍按单批 ≤100 条、
  失败不写入设计，避免限流与部分写入；如需提速应做有界并发 + 令牌桶，
  并把 429 视为可重试、402/401 视为不可重试。

评测引擎只读数据集与预测，写文件由调用方指定路径；本脚本不会修改数据集。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.classifiers.base import ALL_CATEGORIES, ClassificationResult  # noqa: E402
from src.classifiers.deepseek import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PROMPT_VERSION,
    DeepSeekClassifier,
    DeepSeekConfigurationError,
)
from src.classifiers.rule import RuleClassifier  # noqa: E402
from src.evaluation.attribution import build_badcases, count_layers  # noqa: E402
from src.evaluation.cost import estimate_cost  # noqa: E402
from src.evaluation.latency import summarize_latency  # noqa: E402
from src.evaluation.metrics import ALL_CATEGORIES as METRIC_CATEGORIES  # noqa: E402
from src.evaluation.metrics import compute_metrics  # noqa: E402

RULE_MODEL = "rule-keyword-v1"
RULE_PROMPT_VERSION = "none"
DEFAULT_DATASET = "evals/feedback_eval_v1.csv"
REQUIRED_COLUMNS = ("eval_id", "feedback_text", "golden_category")
PREDICTION_COLUMNS = (
    "eval_id",
    "predicted_category",
    "predicted_impact",
    "confidence",
    "reason",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "error",
)
BAD_CASE_COLUMNS = (
    "eval_id",
    "feedback_text",
    "golden_category",
    "predicted_category",
    "confidence",
    "layer",
    "reason",
    "proposed_fix",
)


# ---------------------------------------------------------------------------
# 数据加载与校验
# ---------------------------------------------------------------------------


def load_dataset(path: str | Path, limit: int | None = None) -> list[dict[str, object]]:
    """读取评测集 CSV 并做严格校验；返回按文件顺序的行列表。"""
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"评测数据集不存在：{dataset_path}")
    with dataset_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"评测数据集缺少必需列：{missing}（实际列：{fieldnames}）")
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"评测数据集为空：{dataset_path}")
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=2):  # 第 2 行是第一条数据
        eval_id = str(row.get("eval_id") or "").strip()
        if not eval_id:
            raise ValueError(f"第 {index} 行 eval_id 为空")
        if eval_id in seen_ids:
            raise ValueError(f"第 {index} 行 eval_id 重复：{eval_id}")
        seen_ids.add(eval_id)
        golden = str(row.get("golden_category") or "").strip()
        if golden not in METRIC_CATEGORIES:
            raise ValueError(f"第 {index} 行 golden_category 非法：{golden!r}，必须属于 {METRIC_CATEGORIES}")
        row["eval_id"] = eval_id
        row["golden_category"] = golden
        row["golden_impact_level"] = _parse_impact_level(row.get("golden_impact_level"), index)
        row["rating"] = _parse_optional_int(row.get("rating"))
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return rows


def _parse_impact_level(value: object, index: int) -> int | None:
    """golden_impact_level 允许缺失，但非空值必须是 1-5 的整数。"""
    if value is None or str(value).strip() == "":
        return None
    parsed = _parse_optional_int(value)
    if parsed is None or not 1 <= parsed <= 5:
        raise ValueError(f"第 {index} 行 golden_impact_level 非法：{value!r}，必须是 1-5 的整数")
    return parsed


def _parse_optional_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def build_classifier_record(row: Mapping[str, object]) -> dict[str, object]:
    """把评测集行转成分类器入参（不泄露 golden 标签给模型）。"""
    rating = row.get("rating")
    return {
        "feedback_text": str(row.get("feedback_text", "")),
        # 规则分类器按 rating 推导影响度，缺失时给中性值 3，避免 int(None) 崩溃。
        "rating": rating if rating is not None else 3,
        "country": row.get("country", ""),
        "user_type": row.get("user_type", ""),
        "product_category": row.get("product_category", ""),
    }


# ---------------------------------------------------------------------------
# 单条分类（rule / deepseek），可注入 classifier 便于测试
# ---------------------------------------------------------------------------


def classify_rule(row: Mapping[str, object]) -> tuple[ClassificationResult, dict[str, object]]:
    started = time.perf_counter()
    result = RuleClassifier().classify(build_classifier_record(row))
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return result, {
        "latency_ms": latency_ms,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def classify_deepseek_with_retry(
    row: Mapping[str, object],
    classifier: DeepSeekClassifier,
    max_attempts: int = 2,
) -> tuple[ClassificationResult, dict[str, object]]:
    """分类一条；失败重试 1 次（max_attempts=2），仍失败抛最后一层异常。"""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return classifier.classify_with_meta(build_classifier_record(row))
        except Exception as error:  # noqa: BLE001 - 统一在评测层汇总失败
            last_error = error
            if attempt < max_attempts:
                time.sleep(0.5)
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# 一次评测运行（纯函数，返回装配好的结果 dict）
# ---------------------------------------------------------------------------


def evaluate(
    rows: Sequence[Mapping[str, object]],
    mode: str,
    classify: Callable[[Mapping[str, object]], tuple[ClassificationResult, Mapping[str, object]]],
    aborts_on_error: bool = False,
) -> dict[str, object]:
    """逐条分类并汇总预测行；返回 ``{predictions, failures, elapsed_s}``。

    ``aborts_on_error=True`` 时，任一条最终失败会立刻停止并把失败信息放入
    ``failures``（deepseek 模式整批中止语义）；否则记录错误并继续（rule/replay）。
    """
    predictions: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    started = time.perf_counter()
    for row in rows:
        eval_id = str(row["eval_id"])
        try:
            result, meta = classify(row)
        except Exception as error:  # noqa: BLE001 - 记录可解释的失败原因
            failures.append(
                {
                    "eval_id": eval_id,
                    "attempts": 2,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            if aborts_on_error:
                break
            predictions.append(
                {
                    "eval_id": eval_id,
                    "predicted_category": "",
                    "predicted_impact": "",
                    "confidence": "",
                    "reason": "",
                    "latency_ms": "",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            continue
        predictions.append(
            {
                "eval_id": eval_id,
                "predicted_category": result.category,
                "predicted_impact": result.impact_level,
                "confidence": result.confidence,
                "reason": result.reason,
                "latency_ms": meta.get("latency_ms", 0),
                "prompt_tokens": meta.get("prompt_tokens", 0),
                "completion_tokens": meta.get("completion_tokens", 0),
                "error": "",
            }
        )
    return {
        "predictions": predictions,
        "failures": failures,
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


def assemble_result(
    *,
    mode: str,
    model: str,
    prompt_version: str,
    dataset: str,
    rows: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
    n_errors: int,
    run_time: datetime,
) -> dict[str, object]:
    """按固定 schema 装配结果 JSON（不含文件写入）。"""
    by_id = {str(prediction["eval_id"]): prediction for prediction in predictions}
    scored_rows = [row for row in rows if str(row["eval_id"]) in by_id]
    goldens = [str(row["golden_category"]) for row in scored_rows]
    predicted_categories = [str(by_id[str(row["eval_id"])]["predicted_category"]) for row in scored_rows]
    predicted_categories = [p if p in ALL_CATEGORIES else "待确认" for p in predicted_categories]
    golden_impacts = [row.get("golden_impact_level") for row in scored_rows]
    predicted_impacts = [by_id[str(row["eval_id"])]["predicted_impact"] for row in scored_rows]

    metrics = compute_metrics(goldens, predicted_categories, golden_impacts, predicted_impacts)

    latency_values = [
        float(by_id[str(row["eval_id"])]["latency_ms"])
        for row in scored_rows
        if str(by_id[str(row["eval_id"])].get("latency_ms", "")) not in {"", "None"}
    ]
    latency = summarize_latency(latency_values, n_errors=n_errors)

    prompt_tokens = sum(int(p.get("prompt_tokens") or 0) for p in predictions)
    completion_tokens = sum(int(p.get("completion_tokens") or 0) for p in predictions)
    if mode == "rule":
        cost = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cny": 0.0,
            "pricing_note": "规则基线为本地关键词匹配，不调用付费 API，token 成本为 0；"
            "延迟含 Python 关键词匹配耗时，可在无网络/无密钥时作为降级基线复跑。",
        }
    else:
        cost = estimate_cost(prompt_tokens, completion_tokens, model=model, run_time=run_time)

    timestamp = run_time.astimezone(timezone.utc).isoformat(timespec="seconds")
    run_id = f"{mode}-{run_time.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    return {
        "run_id": run_id,
        "mode": mode,
        "model": model,
        "prompt_version": prompt_version,
        "dataset": dataset,
        "n": len(scored_rows),
        "timestamp": timestamp,
        "metrics": metrics,
        "cost": cost,
        "latency": latency,
        "failures": list(failures),
    }


def build_badcases_for_run(
    rows: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
    mode: str,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    """从预测明细生成 Badcase 列表（调用 attribution 启发式+人工覆盖）。"""
    by_id = {str(prediction["eval_id"]): prediction for prediction in predictions}
    return build_badcases(rows, by_id, mode=mode, overrides=overrides)


# ---------------------------------------------------------------------------
# 输出（JSON / CSV / markdown 摘要）
# ---------------------------------------------------------------------------


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_predictions_csv(path: str | Path, predictions: Sequence[Mapping[str, object]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PREDICTION_COLUMNS))
        writer.writeheader()
        for prediction in predictions:
            writer.writerow({column: prediction.get(column, "") for column in PREDICTION_COLUMNS})


def write_badcases_csv(path: str | Path, badcases: Sequence[Mapping[str, str]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BAD_CASE_COLUMNS))
        writer.writeheader()
        for badcase in badcases:
            writer.writerow({column: badcase.get(column, "") for column in BAD_CASE_COLUMNS})


def read_predictions(path: str | Path) -> list[dict[str, object]]:
    """replay 模式读取预测明细（支持 CSV / JSONL）。"""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"预测明细不存在：{source}")
    if source.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _fmt(value: object, digits: int = 4) -> str:
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown_summary(
    result: Mapping[str, object],
    badcases: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
) -> str:
    """stdout 一页 markdown 摘要（可直接贴进 docs）。"""
    metrics = result["metrics"]
    cost = result["cost"]
    latency = result["latency"]
    per_class = metrics["per_class"]
    key_recall = metrics["key_class_recall"]
    layer_counts = count_layers(badcases)
    n = result["n"]
    lines = [
        f"## VoiceBoard 分类评测摘要（{result['mode']} / {result['model']}）",
        "",
        f"- 数据集：`{result['dataset']}`，样本 n={n}，"
        f"prompt_version={result['prompt_version']}，运行时间 {result['timestamp']}",
        f"- 业务类准确率：{_fmt(metrics['accuracy_business'])}；"
        f"端到端准确率：{_fmt(metrics['accuracy_e2e'])}；"
        f"macro recall（业务类）：{_fmt(metrics['macro_recall_business'])}",
        f"- 关键类召回：物流 {_fmt(key_recall['物流'])}、支付 {_fmt(key_recall['支付'])}、"
        f"商品质量 {_fmt(key_recall['商品质量'])}",
        f"- 待确认：{metrics['uncertain_count']} 条（{_fmt(metrics['uncertain_rate'])}）；"
        f"业务→待确认 {_fmt(metrics['business_to_uncertain_rate'])}；"
        f"待确认→业务 {_fmt(metrics['uncertain_to_business_rate'])}；"
        f"人工修订率估计 {_fmt(metrics['human_revision_rate_estimate'])}",
        f"- 影响度：MAE {_fmt(metrics['impact_mae'], 3)}，完全一致率 {_fmt(metrics['impact_exact_rate'])}",
        f"- 成本：{cost['total_tokens']} tokens，估算 ￥{cost['estimated_cny']}；"
        f"按单批 100 条线性外推约 ￥{_fmt(_batch_cost(result), 4)}",
        f"- 延迟：p50 {latency['p50_ms']} ms，p95 {latency['p95_ms']} ms，"
        f"均值 {latency['mean_ms']} ms，总耗时 {latency['total_s']} s，失败 {latency['n_errors']} 条",
        f"- Badcase：{len(badcases)} 条；四层计数 "
        + "、".join(f"{layer} {layer_counts[layer]}" for layer in count_layers(badcases)),
        "",
        "| 类别 | precision | recall | f1 | support |",
        "|---|---|---|---|---|",
    ]
    for category in METRIC_CATEGORIES:
        row = per_class[category]
        lines.append(
            f"| {category} | {_fmt(row['precision'], 3)} | {_fmt(row['recall'], 3)} | "
            f"{_fmt(row['f1'], 3)} | {row['support']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _batch_cost(result: Mapping[str, object]) -> float:
    cost = result["cost"]
    n = int(result.get("n") or 0)
    if not n:
        return 0.0
    return float(cost["estimated_cny"]) / n * 100


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def read_dotenv(path: str | Path, names: Sequence[str]) -> dict[str, str]:
    """从 .env 读取指定变量（不打印值）；格式 ``KEY=VALUE``，忽略注释。"""
    values: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in names:
            values[key] = value.strip().strip('"').strip("'")
    return values


def resolve_api_key(env_name: str, env_file: str | Path) -> str:
    key = os.getenv(env_name, "").strip()
    if key:
        return key
    return read_dotenv(env_file, [env_name]).get(env_name, "").strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VoiceBoard 分类评测（rule / deepseek / replay）")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--mode", required=True, choices=("rule", "deepseek", "replay"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--predictions-out", default=None)
    parser.add_argument("--predictions-in", default=None, help="replay 模式的预测明细 CSV/JSONL")
    parser.add_argument("--badcases-out", default=None)
    parser.add_argument("--attribution-overrides", default=None)
    parser.add_argument("--failures-out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--env-file", default=str(PROJECT_ROOT / ".env"))
    parser.add_argument("--prompt-version", default=None)
    return parser.parse_args(argv)


def _resolve_prompt_version(mode: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    return RULE_PROMPT_VERSION if mode == "rule" else PROMPT_VERSION


def _resolve_model(
    mode: str, explicit: str | None, dotenv: Mapping[str, str] | None = None
) -> str:
    if mode == "rule":
        return RULE_MODEL
    return (
        explicit
        or os.getenv("DEEPSEEK_MODEL", "").strip()
        or (dotenv or {}).get("DEEPSEEK_MODEL", "").strip()
        or DEFAULT_MODEL
    )


def _resolve_base_url(
    explicit: str | None, dotenv: Mapping[str, str] | None = None
) -> str:
    return (
        explicit
        or os.getenv("DEEPSEEK_BASE_URL", "").strip()
        or (dotenv or {}).get("DEEPSEEK_BASE_URL", "").strip()
        or DEFAULT_BASE_URL
    )


def _relative_dataset(path: str | Path) -> str:
    dataset_path = Path(path).resolve()
    try:
        return dataset_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return dataset_path.as_posix()


def _write_failures_and_exit(
    *,
    args: argparse.Namespace,
    rows: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
    elapsed_s: float,
) -> int:
    failures_path = (
        Path(args.failures_out)
        if args.failures_out
        else Path(str(args.out) + ".failures.json")
    )
    payload = {
        "mode": args.mode,
        "dataset": _relative_dataset(args.dataset),
        "n_attempted": len(predictions) + len(failures),
        "n_completed": len(predictions),
        "failed_eval_id": failures[0]["eval_id"] if failures else None,
        "failures": list(failures),
        "partial_predictions": list(predictions),
        "elapsed_s": elapsed_s,
        "note": "DeepSeek 调用失败重试 1 次后仍失败，整批中止；按应用“失败不写入”设计，"
        "未产出正式结果 JSON/预测 CSV/Badcase CSV。",
    }
    write_json(failures_path, payload)
    print(
        f"[FAIL] 第 {payload['n_attempted']} 条失败（eval_id={payload['failed_eval_id']}），"
        f"已写失败清单 {failures_path}；未产出正式结果。",
        file=sys.stderr,
    )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    # Windows 控制台可能是 GBK 等窄编码；摘要含中文/货币符号，用 replace 兜底避免
    # 评测跑完后只因打印失败而崩掉（结果文件此时已写好）。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover - 仅防御性
                pass
    args = parse_args(argv)
    rows = load_dataset(args.dataset, limit=args.limit)
    run_time = datetime.now(timezone.utc)
    dotenv = read_dotenv(
        args.env_file, ["DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"]
    )
    model = _resolve_model(args.mode, args.model, dotenv)
    base_url = _resolve_base_url(args.base_url, dotenv)
    prompt_version = _resolve_prompt_version(args.mode, args.prompt_version)
    overrides: dict[str, Mapping[str, str]] = {}
    if args.attribution_overrides:
        overrides_path = Path(args.attribution_overrides)
        if overrides_path.exists():
            overrides = json.loads(overrides_path.read_text(encoding="utf-8"))

    if args.mode == "rule":
        run = evaluate(rows, mode="rule", classify=classify_rule)
        predictions = run["predictions"]
        failures = run["failures"]
        n_errors = len(failures)
        mode_for_badcases = "rule"
    elif args.mode == "deepseek":
        api_key = resolve_api_key(args.api_key_env, args.env_file)
        if not api_key:
            print(
                f"[ERROR] 未找到 {args.api_key_env}：请写入 {args.env_file} 或设置环境变量后重试。",
                file=sys.stderr,
            )
            return 3
        try:
            classifier = DeepSeekClassifier(
                api_key=api_key, base_url=base_url, model=model
            )
        except DeepSeekConfigurationError as error:
            print(f"[ERROR] {error}", file=sys.stderr)
            return 3
        del api_key  # 不在后续流程中持有/打印密钥
        run = evaluate(
            rows,
            mode="deepseek",
            classify=lambda row: classify_deepseek_with_retry(row, classifier),
            aborts_on_error=True,
        )
        predictions = run["predictions"]
        failures = run["failures"]
        if failures:
            return _write_failures_and_exit(
                args=args,
                rows=rows,
                predictions=predictions,
                failures=failures,
                elapsed_s=run["elapsed_s"],
            )
        n_errors = 0
        mode_for_badcases = "deepseek"
    else:  # replay
        if not args.predictions_in:
            print("[ERROR] replay 模式必须提供 --predictions-in", file=sys.stderr)
            return 3
        raw_predictions = read_predictions(args.predictions_in)
        predictions = [
            {
                "eval_id": str(item.get("eval_id", "")),
                "predicted_category": item.get("predicted_category", ""),
                "predicted_impact": item.get("predicted_impact", ""),
                "confidence": item.get("confidence", ""),
                "reason": item.get("reason", ""),
                "latency_ms": item.get("latency_ms", "") or 0,
                "prompt_tokens": int(float(item.get("prompt_tokens") or 0)),
                "completion_tokens": int(float(item.get("completion_tokens") or 0)),
                "error": item.get("error", ""),
            }
            for item in raw_predictions
        ]
        failures = [
            {"eval_id": str(item.get("eval_id", "")), "attempts": 0, "error": str(item["error"])}
            for item in predictions
            if str(item.get("error") or "")
        ]
        n_errors = len(failures)
        predictions = [item for item in predictions if not str(item.get("error") or "")]
        run = {"elapsed_s": 0.0}
        mode_for_badcases = "deepseek" if "deepseek" in str(args.predictions_in).lower() else "rule"

    result = assemble_result(
        mode=args.mode,
        model=model,
        prompt_version=prompt_version,
        dataset=_relative_dataset(args.dataset),
        rows=rows,
        predictions=predictions,
        failures=failures,
        n_errors=n_errors,
        run_time=run_time,
    )
    if not predictions:
        print("[ERROR] 没有任何有效预测，无法产出结果。", file=sys.stderr)
        return 2

    badcases = build_badcases_for_run(rows, predictions, mode_for_badcases, overrides)
    out_path = Path(args.out)
    predictions_out = (
        Path(args.predictions_out)
        if args.predictions_out
        else out_path.with_name(
            f"predictions_{args.mode}_v1.csv"
            if args.mode != "replay"
            else "predictions_replay_v1.csv"
        )
    )
    badcases_out = (
        Path(args.badcases_out)
        if args.badcases_out
        else out_path.with_name("badcases_v1.csv")
    )
    write_json(out_path, result)
    write_predictions_csv(predictions_out, predictions)
    write_badcases_csv(badcases_out, badcases)
    print(render_markdown_summary(result, badcases, predictions))
    print(f"\n结果 JSON：{out_path}")
    print(f"预测明细：{predictions_out}")
    print(f"Badcase：{badcases_out}（{len(badcases)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
