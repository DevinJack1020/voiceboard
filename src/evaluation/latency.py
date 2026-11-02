"""延迟汇总（纯函数）。

口径：

- 单条延迟 = 一次分类调用的 wall-clock 时间（毫秒），包含该次调用内部的重试；
  规则模式包含关键词匹配耗时，DeepSeek 模式包含一次 HTTP 往返。
- ``p50_ms`` / ``p95_ms`` 用线性插值分位数（numpy 默认口径），样本少时依然稳定。
- ``mean_ms`` 为算术平均；``total_s`` 为全部样本延迟之和（秒）。
- ``n_errors`` 为运行期错误条数；错误的样本不计入延迟分位数，避免失败请求
  把尾部延迟统计污染，错误详情见结果 JSON 的 ``failures``。
- 空样本时全部指标记 0.0，不抛异常。
"""

from __future__ import annotations

import math
from typing import Sequence


def percentile(values: Sequence[float], p: float) -> float:
    """线性插值分位数；``p`` 取 0-100。空序列返回 0.0。"""
    if not 0 <= p <= 100:
        raise ValueError(f"分位数必须在 0-100 之间，收到 {p!r}")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def summarize_latency(
    latencies_ms: Sequence[float], n_errors: int = 0
) -> dict[str, float | int]:
    """汇总延迟统计，字段与结果 JSON 的 ``latency`` 一致。"""
    values = [float(value) for value in latencies_ms if value is not None]
    total_ms = sum(values)
    return {
        "p50_ms": round(percentile(values, 50), 3),
        "p95_ms": round(percentile(values, 95), 3),
        "mean_ms": round(total_ms / len(values), 3) if values else 0.0,
        "total_s": round(total_ms / 1000, 3),
        "n_errors": int(n_errors),
    }
