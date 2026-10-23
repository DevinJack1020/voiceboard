from __future__ import annotations

from src.classifiers.base import ClassificationResult


CATEGORY_TERMS = {
    "物流": (
        "物流", "快递", "包裹", "配送", "发货", "到货",
        "shipping", "delivery", "parcel", "courier",
    ),
    "支付": (
        "支付", "付款", "扣款", "信用卡", "收款", "结账",
        "payment", "checkout", "charged", "card declined",
    ),
    "商品质量": (
        "质量", "破损", "假货", "瑕疵", "坏了", "杂音",
        "quality", "damaged", "defective", "fake", "broken",
    ),
    "搜索推荐": (
        "搜索", "推荐", "找不到", "排序", "不相关",
        "search", "recommendation", "ranking", "irrelevant",
    ),
    "客服": (
        "客服", "客户服务", "联系不上", "回复", "人工服务",
        "support", "customer service", "agent", "no reply",
    ),
    "退换货": (
        "退款", "退货", "换货", "退换", "退回",
        "refund", "return", "exchange", "money back",
    ),
}

HIGH_IMPACT_TERMS = (
    "无法付款",
    "付款失败",
    "重复扣款",
    "丢件",
    "假货",
    "退款失败",
    "账号冻结",
    "cannot pay",
    "double charged",
    "lost parcel",
)


class RuleClassifier:
    def classify(self, record: dict) -> ClassificationResult:
        text = " ".join(str(record.get("feedback_text", "")).casefold().split())
        scores = {
            category: sum(1 for term in terms if term.casefold() in text)
            for category, terms in CATEGORY_TERMS.items()
        }
        top_score = max(scores.values(), default=0)
        leaders = [category for category, score in scores.items() if score == top_score]

        if top_score == 0:
            category = "待确认"
            confidence = 0.0
            reason = "未命中可解释的分类关键词"
        elif len(leaders) > 1:
            category = "待确认"
            confidence = 0.4
            reason = f"多个分类得分并列：{'、'.join(leaders)}"
        else:
            category = leaders[0]
            total_score = sum(scores.values())
            confidence = min(0.95, 0.65 + 0.1 * top_score)
            if total_score > top_score:
                confidence = min(confidence, top_score / total_score)
            hits = [term for term in CATEGORY_TERMS[category] if term.casefold() in text]
            reason = f"命中关键词：{'、'.join(hits)}"

        impact = record.get("impact_level")
        if impact is None:
            rating = int(record.get("rating", 3))
            impact = 6 - rating
            if any(term.casefold() in text for term in HIGH_IMPACT_TERMS):
                impact += 1
        impact = max(1, min(5, int(impact)))

        return ClassificationResult(
            category=category,
            impact_level=impact,
            confidence=round(confidence, 2),
            reason=reason,
            source="rule",
        )
