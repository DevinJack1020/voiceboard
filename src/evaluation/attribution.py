"""Badcase 四层归因辅助（启发式 + 人工覆盖）。

分层口径（与 ``evals/results/badcases_v1.csv`` 的 ``layer`` 列一致）：

- **数据**：golden 本身有歧义、缺少上下文或标注口径不一致；改进动作在标注/数据侧。
- **提示词**：类别边界、多意图主诉求、反讽/中英混排等未被 prompt 明确定义；
  改进动作在 prompt/示例侧。
- **规则**：关键词未命中、误命中、多类并列、待确认阈值不合理；改进动作在
  规则词典/权重/阈值侧（主要针对规则基线）。
- **交互**：模型低置信输出待确认后，交互层缺少候选、快速确认路径或影响度
  展示/修订入口；改进动作在产品交互侧。

本模块给出**启发式初判**（确定性、可测试），真实错例的最终 layer/理由/改进
建议由评测人逐条复核，可用 ``overrides`` 覆盖：

``{"eval_id": {"layer": "提示词", "reason": "...", "proposed_fix": "..."}}``
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.classifiers.base import ALL_CATEGORIES, BUSINESS_CATEGORIES
from src.evaluation.metrics import UNCERTAIN

LAYERS = ("数据", "提示词", "规则", "交互")

BAD_LAYER_RUBRIC: dict[str, str] = {
    "数据": "golden 歧义/缺上下文/标注口径不一致，改进在标注与数据补充",
    "提示词": "类别边界、多意图、反讽、中英混排等未被 prompt 覆盖，改进在 prompt 与示例",
    "规则": "关键词未命中/误命中、多类并列、待确认阈值不合理，改进在词典/权重/阈值",
    "交互": "待确认展示、人工复核路径、影响度展示/修订入口缺失，改进在产品交互",
}

# 规则分类器关键词表（用于判断文本是否同时命中多个类别 → 多意图证据）。
_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "物流": ("物流", "快递", "包裹", "配送", "发货", "到货", "shipping", "delivery", "parcel", "courier"),
    "支付": ("支付", "付款", "扣款", "信用卡", "收款", "结账", "payment", "checkout", "charged", "card declined"),
    "商品质量": ("质量", "破损", "假货", "瑕疵", "坏了", "杂音", "quality", "damaged", "defective", "fake", "broken"),
    "搜索推荐": ("搜索", "推荐", "找不到", "排序", "不相关", "search", "recommendation", "ranking", "irrelevant"),
    "客服": ("客服", "客户服务", "联系不上", "回复", "人工服务", "support", "customer service", "agent", "no reply"),
    "退换货": ("退款", "退货", "换货", "退换", "退回", "refund", "return", "exchange", "money back"),
}

# 常见易混类别对（提示词层应显式区分边界）。
_BOUNDARY_PAIRS = frozenset(
    {
        frozenset({"商品质量", "退换货"}),
        frozenset({"物流", "退换货"}),
        frozenset({"支付", "退换货"}),
        frozenset({"商品质量", "物流"}),
        frozenset({"搜索推荐", "商品质量"}),
        frozenset({"客服", "退换货"}),
    }
)


def category_terms_hit(text: str) -> list[str]:
    """返回文本命中的业务类别（按 ``CATEGORY_TERMS`` 的关键词表）。"""
    lowered = " ".join(str(text or "").casefold().split())
    hits = []
    for category, terms in _CATEGORY_TERMS.items():
        if any(term.casefold() in lowered for term in terms):
            hits.append(category)
    return hits


def _best_guess(mode: str, golden: str, predicted: str, confidence: float, text: str) -> tuple[str, str, str]:
    """启发式返回 ``(layer, reason, proposed_fix)``。"""
    hits = category_terms_hit(text)
    prefix = "规则基线（关键词词表）" if mode == "rule" else "DeepSeek 零样本"
    confidence_text = f"模型置信度 {confidence:.2f}"

    if golden == UNCERTAIN:
        if mode == "rule":
            term_text = "、".join(t for t in _CATEGORY_TERMS.get(predicted, ()) if t.casefold() in str(text).casefold())
            return (
                "规则",
                f"{prefix}命中关键词（{term_text or '疑似命中词'}）把本应待确认的边界文本强行归为「{predicted}」；"
                f"golden 为待确认（{confidence_text}）。",
                "为高频误命中词增加否定/上下文约束，或把低分命中降级为待确认；边界文本进入人工复核。",
            )
        return (
            "数据",
            f"golden 标为待确认（无法归入单一业务类），{prefix}仍给出「{predicted}」（{confidence_text}）；"
            "属标注边界或反馈上下文不足，需复核该条 golden 与 label_note。",
            "复核该条标注（保留待确认/细化类别）；若确认模型过度自信，在 prompt 增加“证据不足输出待确认”约束并补充示例。",
        )

    if predicted == UNCERTAIN:
        if mode == "rule":
            return (
                "规则",
                f"{prefix}未命中「{golden}」相关关键词（或多类并列）而降级为待确认，{confidence_text}。",
                f"补充「{golden}」同义词/中英混排词表；并列时按影响度或词权重排序，而不是直接待确认。",
            )
        if confidence <= 0.6:
            return (
                "交互",
                f"{prefix}以低置信（{confidence_text}）输出待确认，业务上应快速人工确认；"
                "当前交互缺少候选类别与命中证据，导致人工修订成本高。",
                "待确认卡片展示 top-2 候选类别与理由，支持一键采纳/改判并记录 revision，形成修订率可观测指标。",
            )
        return (
            "提示词",
            f"{prefix}未利用文本中对「{golden}」的判别线索而输出待确认（{confidence_text}），属 prompt 判别特征/示例不足。",
            f"在 prompt 补充「{golden}」的判别特征与边界 few-shot 示例，并明确“有明确诉求时不得输出待确认”。",
        )

    # 业务类之间的混淆。
    predicted_terms = "、".join(
        t for t in _CATEGORY_TERMS.get(predicted, ()) if t.casefold() in str(text).casefold()
    )
    golden_terms = "、".join(
        t for t in _CATEGORY_TERMS.get(golden, ()) if t.casefold() in str(text).casefold()
    )
    if mode == "rule":
        reason = (
            f"{prefix}按词频把文本判为「{predicted}」"
            + (f"（命中：{predicted_terms}）" if predicted_terms else "")
            + f"，而 golden 为「{golden}」"
            + (f"（命中：{golden_terms}）" if golden_terms else "")
            + "；规则无法理解主诉求与语义边界。"
        )
        return (
            "规则",
            reason,
            f"补充「{golden}」强信号词并为易混词加权/加否定上下文；规则基线仅作降级兜底，语义边界交给 LLM。",
        )

    if len(hits) >= 2:
        return (
            "提示词",
            f"文本同时命中多个类别（{'、'.join(hits)}），{prefix}选了「{predicted}」而 golden 为主诉求「{golden}」；"
            "prompt 未定义多意图时如何选主痛点。",
            "在 prompt 明确主痛点判定规则（按用户核心诉求与损失程度选主类），并加入多意图 few-shot 示例。",
        )
    if frozenset({golden, predicted}) in _BOUNDARY_PAIRS:
        return (
            "提示词",
            f"「{golden}」与「{predicted}」是相邻业务类别，{prefix}边界判断偏移（{confidence_text}）；"
            "prompt 缺少两类的区分定义与示例。",
            f"在 prompt 增加「{golden} vs {predicted}」的边界定义与 1-2 个对照示例，必要时把判断拆成“诉求 → 类别”两步。",
        )
    return (
        "提示词",
        f"{prefix}把「{golden}」判为「{predicted}」（{confidence_text}）；"
        "属类别定义/关键词与语义理解偏差，改进在 prompt 判别特征与示例。",
        f"补充「{golden}」的判别特征、反例与 few-shot；对反讽/中英混排/超短文本增加专门示例。",
    )


def build_badcases(
    rows: Sequence[Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, object]],
    mode: str,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    """为类别错例生成 Badcase 记录列表。

    ``rows`` 为数据集行（需含 eval_id/feedback_text/golden_category）；
    ``predictions`` 为 ``eval_id -> 预测行``（需含 predicted_category 与 confidence）；
    ``mode`` 为 ``rule`` / ``deepseek``，用于选择归因策略；
    ``overrides`` 为人工复核后的覆盖值，优先于启发式结果。

    Badcase 定义为 category 不一致（含 golden=待确认 的误判），返回字段与
    ``evals/results/badcases_v1.csv`` 列完全一致。
    """
    overrides = overrides or {}
    badcases: list[dict[str, str]] = []
    for row in rows:
        eval_id = str(row["eval_id"])
        golden = str(row["golden_category"])
        prediction = predictions.get(eval_id)
        if prediction is None:
            continue
        predicted = str(prediction.get("predicted_category") or "")
        if predicted not in ALL_CATEGORIES:
            predicted = UNCERTAIN  # 非法预测按待确认处理，保证可归因
        if golden == predicted:
            continue
        confidence = float(prediction.get("confidence") or 0.0)
        layer, reason, proposed_fix = _best_guess(mode, golden, predicted, confidence, str(row.get("feedback_text", "")))
        override = overrides.get(eval_id) or {}
        layer = str(override.get("layer") or layer)
        if layer not in LAYERS:
            raise ValueError(f"{eval_id} 的归因 layer 非法：{layer!r}，必须属于 {LAYERS}")
        badcases.append(
            {
                "eval_id": eval_id,
                "feedback_text": str(row.get("feedback_text", "")),
                "golden_category": golden,
                "predicted_category": predicted,
                "confidence": f"{confidence:.2f}",
                "layer": layer,
                "reason": str(override.get("reason") or reason),
                "proposed_fix": str(override.get("proposed_fix") or proposed_fix),
            }
        )
    return badcases


def count_layers(badcases: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """按 layer 计数（保证四层都出现，便于文档/页面展示）。"""
    counts = {layer: 0 for layer in LAYERS}
    for case in badcases:
        layer = str(case.get("layer", ""))
        if layer in counts:
            counts[layer] += 1
    return counts


def badcase_rate(badcases: Sequence[Mapping[str, object]], n: int) -> float:
    """Badcase 占全部样本的比例（除零返回 0.0）。"""
    return len(badcases) / n if n else 0.0
