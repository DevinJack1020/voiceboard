from __future__ import annotations

from src.repository import VoiceBoardRepository


ROADMAP_STATUSES = ("待评估", "已规划", "开发中", "已上线")


class RoadmapService:
    def __init__(self, repository: VoiceBoardRepository):
        self.repository = repository

    def list_items(
        self,
        include_archived: bool = False,
        owner: str | None = None,
        target_version: str | None = None,
    ) -> list[dict]:
        items = self.repository.list_roadmap_items(include_archived)
        return [
            item
            for item in items
            if (not owner or item["owner"] == owner)
            and (not target_version or item["target_version"] == target_version)
        ]

    def update_item(
        self,
        item_id: int,
        title: str,
        solution: str,
        owner: str,
        status: str,
        target_version: str,
    ) -> None:
        cleaned_title = title.strip()
        cleaned_solution = solution.strip()
        if not cleaned_title:
            raise ValueError("需求标题不能为空")
        if not cleaned_solution:
            raise ValueError("产品方案不能为空")
        if status not in ROADMAP_STATUSES:
            raise ValueError("需求状态无效")
        self.repository.update_roadmap_item(
            item_id,
            title=cleaned_title[:200],
            solution=cleaned_solution[:4000],
            owner=owner.strip()[:100],
            status=status,
            target_version=target_version.strip()[:100],
        )

    def archive_item(self, item_id: int) -> None:
        self.repository.set_roadmap_archived(item_id, True)

    def restore_item(self, item_id: int) -> None:
        self.repository.set_roadmap_archived(item_id, False)
