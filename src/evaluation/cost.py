"""DeepSeek API 成本估算（纯函数）。

单价来源（2026-11-02 通过官方文档核实，非拍脑袋）：

    https://api-docs.deepseek.com/zh-cn/quick_start/pricing
    https://api-docs.deepseek.com/quick_start/pricing

官方当前价目表（人民币，每 100 万 tokens）：

    deepseek-flash
      输入（缓存命中）：空闲 0.02 元 / 高峰 0.04 元
      输入（缓存未命中）：空闲 1 元 / 高峰 2 元
      输出：空闲 4 元 / 高峰 8 元
    deepseek-v4-pro
      输入（缓存命中）：空闲 0.15 元 / 高峰 0.30 元
      输入（缓存未命中）：空闲 4.5 元 / 高峰 9.0 元
      输出：空闲 13.5 元 / 高峰 27.0 元

计价口径：

- 默认按"全部输入为缓存未命中"估算，是保守上限（系统提示词在多条样本间
  重复，实际可能有缓存命中，实付只会更低）；``assume_cache_hit=True`` 时
  按缓存命中价估算下限。
- 高峰时段（北京时间周一至周五 9:00-12:00、14:00-18:00）单价为空闲时段的
  2 倍；节假日按官方"法定节假日全天空闲"处理，本函数不内置节假日日历，
  若运行日恰逢节假日，估算会偏高（在 ``pricing_note`` 中注明）。
- 模型名不在官方价目表时（例如历史遗留模型名）回退到 ``deepseek-flash``
  单价估算，并在 ``pricing_note`` 中显式说明，不静默使用未知价格。
- 本模块不处理 Search/Fetch 等独立计费 API（本评测只调用 chat completions）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CNY_PER_MILLION: dict[str, dict[str, dict[str, float]]] = {
    "deepseek-flash": {
        "input_cache_hit": {"off_peak": 0.02, "peak": 0.04},
        "input_cache_miss": {"off_peak": 1.0, "peak": 2.0},
        "output": {"off_peak": 4.0, "peak": 8.0},
    },
    "deepseek-v4-pro": {
        "input_cache_hit": {"off_peak": 0.15, "peak": 0.30},
        "input_cache_miss": {"off_peak": 4.5, "peak": 9.0},
        "output": {"off_peak": 13.5, "peak": 27.0},
    },
}
FALLBACK_PRICING_MODEL = "deepseek-flash"
PRICING_SOURCE_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing"
PRICING_FETCHED_AT = "2026-11-02"
BEIJING_TZ = timezone(timedelta(hours=8))  # 中国无夏令时，固定 UTC+8 精确


@dataclass(frozen=True)
class PricingBand:
    """一次运行命中的计价时段。"""

    band: str  # "peak" | "off_peak"
    local_time: str
    note: str


def _coerce_moment(run_time: datetime | str | None) -> datetime:
    if run_time is None:
        return datetime.now(timezone.utc)
    if isinstance(run_time, str):
        moment = datetime.fromisoformat(run_time)
    elif isinstance(run_time, datetime):
        moment = run_time
    else:
        raise TypeError(f"run_time 必须是 datetime 或 ISO 字符串，收到 {type(run_time)!r}")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def is_peak(moment: datetime | str | None = None) -> bool:
    """是否处于 DeepSeek 高峰时段（北京时间工作日 9-12 / 14-18）。"""
    local = _coerce_moment(moment).astimezone(BEIJING_TZ)
    if local.weekday() >= 5:  # 周六、周日全天空闲
        return False
    minutes = local.hour * 60 + local.minute
    return (9 * 60 <= minutes < 12 * 60) or (14 * 60 <= minutes < 18 * 60)


def pricing_band(moment: datetime | str | None = None) -> PricingBand:
    local = _coerce_moment(moment).astimezone(BEIJING_TZ)
    peak = is_peak(local)
    return PricingBand(
        band="peak" if peak else "off_peak",
        local_time=local.isoformat(timespec="seconds"),
        note=(
            "高峰时段（北京时间工作日 9-12/14-18）"
            if peak
            else "空闲时段（含周末/节假日，单价为高峰的一半）"
        ),
    )


def _pricing_for(model: str) -> tuple[str, bool]:
    normalized = (model or "").strip()
    matched = normalized if normalized in CNY_PER_MILLION else None
    return matched or FALLBACK_PRICING_MODEL, matched is None


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = FALLBACK_PRICING_MODEL,
    run_time: datetime | str | None = None,
    assume_cache_hit: bool = False,
) -> dict[str, object]:
    """按官方单价估算一次评测运行的 token 成本。

    返回字段与结果 JSON 的 ``cost`` 一致：
    ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens`` /
    ``estimated_cny`` / ``pricing_note``。
    """
    prompt_tokens = max(0, int(prompt_tokens))
    completion_tokens = max(0, int(completion_tokens))
    total_tokens = prompt_tokens + completion_tokens
    pricing_model, used_fallback = _pricing_for(model)
    band = pricing_band(run_time)
    table = CNY_PER_MILLION[pricing_model]
    input_key = "input_cache_hit" if assume_cache_hit else "input_cache_miss"
    input_rate = table[input_key][band.band]
    output_rate = table["output"][band.band]
    estimated_cny = (
        prompt_tokens / 1_000_000 * input_rate
        + completion_tokens / 1_000_000 * output_rate
    )

    parts = [
        f"官方价目表（{PRICING_FETCHED_AT} 抓取）{PRICING_SOURCE_URL}",
        f"计价模型 {pricing_model}"
        + (f"（请求模型 {model!r} 不在官方价目表，回退按该模型单价估算）" if used_fallback else ""),
        f"输入按{'缓存命中' if assume_cache_hit else '缓存未命中'}"
        f" {input_rate} 元/百万tokens、输出 {output_rate} 元/百万tokens",
        f"运行时段：{band.note}，本地时间 {band.local_time}",
        "高峰时段单价为空闲的 2 倍；未内置中国法定节假日日历，若运行日恰逢节假日估算偏高",
        "未计入 Search/Fetch 等独立计费 API（本评测只调用 chat completions）",
    ]
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cny": round(estimated_cny, 6),
        "pricing_note": "；".join(parts) + "。",
    }


def estimate_batch_cost(
    prompt_tokens: int,
    completion_tokens: int,
    n_samples: int,
    batch_size: int = 100,
    model: str = FALLBACK_PRICING_MODEL,
    run_time: datetime | str | None = None,
) -> dict[str, object]:
    """把一次评测的 token 成本按条数线性外推到 ``batch_size`` 条的批量成本。

    仅用于结果 JSON/文档中的"按单批 100 条估算"说明；外推假设输入输出
    token 线性增长（同一 prompt、同类文本），实际会因文本长度分布略有偏差。
    """
    if n_samples <= 0:
        raise ValueError("n_samples 必须为正整数")
    if batch_size <= 0:
        raise ValueError("batch_size 必须为正整数")
    scale = batch_size / n_samples
    return estimate_cost(
        prompt_tokens=int(round(prompt_tokens * scale)),
        completion_tokens=int(round(completion_tokens * scale)),
        model=model,
        run_time=run_time,
    )
