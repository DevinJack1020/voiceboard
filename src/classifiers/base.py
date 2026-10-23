from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


BUSINESS_CATEGORIES = (
    "物流",
    "支付",
    "商品质量",
    "搜索推荐",
    "客服",
    "退换货",
)
ALL_CATEGORIES = BUSINESS_CATEGORIES + ("待确认",)


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    impact_level: int
    confidence: float
    reason: str
    source: str


class FeedbackClassifier(Protocol):
    def classify(self, record: dict) -> ClassificationResult: ...

