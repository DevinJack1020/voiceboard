from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from src.analytics import top_pain_points
from src.repository import VoiceBoardRepository


SOLUTION_TEMPLATES = {
    "物流": "优化物流节点可视化，增加延迟预警和异常包裹主动通知。",
    "支付": "优化支付失败原因提示，提供备用支付方式和失败后恢复路径。",
    "商品质量": "加强商品质量准入与抽检，完善争议商品举证和治理机制。",
    "搜索推荐": "优化查询理解和排序特征，增加结果相关性反馈入口。",
    "客服": "优化客服分流与响应 SLA，补充高频问题自助解决路径。",
    "退换货": "简化退换货步骤，透明展示审核、寄回和退款进度。",
}


@dataclass(frozen=True)
class PainPoint:
    rank: int
    category: str
    frequency: int
    average_impact: float
    priority_score: float
    filters: dict
    evidence: list[str]
    solution: str


@dataclass(frozen=True)
class RoadmapCreation:
    item_id: int
    created: bool


class InsightService:
    def __init__(self, repository: VoiceBoardRepository):
        self.repository = repository

    def build_insights(self, records: list[dict], filters: dict) -> list[PainPoint]:
        insights: list[PainPoint] = []
        for row in top_pain_points(records):
            evidence = [
                str(record["feedback_text"])
                for record in records
                if record["category"] == row["category"]
            ][:5]
            insights.append(
                PainPoint(
                    rank=row["rank"],
                    category=row["category"],
                    frequency=row["frequency"],
                    average_impact=row["average_impact"],
                    priority_score=row["priority_score"],
                    filters={key: value for key, value in filters.items() if value},
                    evidence=evidence,
                    solution=SOLUTION_TEMPLATES[row["category"]],
                )
            )
        return insights

    def create_roadmap_item(
        self,
        insight: PainPoint,
        solution: str,
        owner: str = "",
        target_version: str = "",
    ) -> RoadmapCreation:
        cleaned_solution = solution.strip()
        if not cleaned_solution:
            raise ValueError("产品方案不能为空")
        snapshot = {
            "category": insight.category,
            "frequency": insight.frequency,
            "average_impact": insight.average_impact,
            "priority_score": insight.priority_score,
            "filters": insight.filters,
        }
        source_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        source_key = hashlib.sha256(source_json.encode("utf-8")).hexdigest()
        item_id, created = self.repository.create_roadmap_item(
            {
                "source_key": source_key,
                "title": f"优化{insight.category}体验",
                "category": insight.category,
                "frequency": insight.frequency,
                "average_impact": insight.average_impact,
                "priority_score": insight.priority_score,
                "filter_snapshot": json.dumps(
                    insight.filters, ensure_ascii=False, sort_keys=True
                ),
                "solution": cleaned_solution[:4000],
                "evidence_summary": json.dumps(
                    insight.evidence, ensure_ascii=False
                ),
                "owner": owner.strip()[:100],
                "target_version": target_version.strip()[:100],
            }
        )
        return RoadmapCreation(item_id=item_id, created=created)
