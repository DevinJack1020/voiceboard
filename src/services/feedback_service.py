from __future__ import annotations

from dataclasses import asdict, dataclass

from src.classifiers.base import BUSINESS_CATEGORIES
from src.repository import VoiceBoardRepository


@dataclass(frozen=True)
class FeedbackFilters:
    country: str | None = None
    user_type: str | None = None
    product_category: str | None = None
    category: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass(frozen=True)
class FeedbackPage:
    records: list[dict]
    total: int
    page: int
    page_size: int


class FeedbackService:
    def __init__(self, repository: VoiceBoardRepository):
        self.repository = repository

    def list_feedback(
        self,
        filters: FeedbackFilters,
        page: int = 1,
        page_size: int = 50,
    ) -> FeedbackPage:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        records, total = self.repository.query_feedback(
            asdict(filters),
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return FeedbackPage(records, total, page, page_size)

    def filter_options(self, column: str) -> list[str]:
        return self.repository.distinct_feedback_values(column)

    def correct_feedback(
        self,
        feedback_id: int,
        category: str,
        impact_level: int,
        reason: str,
    ) -> None:
        if category not in BUSINESS_CATEGORIES:
            raise ValueError("人工分类必须选择六个正式分类之一")
        if not isinstance(impact_level, int) or not 1 <= impact_level <= 5:
            raise ValueError("影响程度必须是 1–5 的整数")
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValueError("请填写人工修订原因")
        self.repository.revise_feedback(
            feedback_id,
            category,
            impact_level,
            cleaned_reason[:500],
        )
