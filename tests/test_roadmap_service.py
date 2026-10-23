import pytest

from src.repository import VoiceBoardRepository
from src.services.roadmap_service import RoadmapService


def seeded_service(tmp_path):
    repository = VoiceBoardRepository(tmp_path / "voiceboard.db")
    repository.initialize()
    item_id, _ = repository.create_roadmap_item(
        {
            "source_key": "snapshot-1",
            "title": "优化物流体验",
            "category": "物流",
            "frequency": 12,
            "average_impact": 4.5,
            "priority_score": 54.0,
            "filter_snapshot": "{}",
            "solution": "增加延迟预警",
            "evidence_summary": "[]",
            "owner": "",
            "target_version": "",
        }
    )
    return repository, RoadmapService(repository), item_id


def test_update_persists_owner_status_version_title_and_solution(tmp_path):
    _, service, item_id = seeded_service(tmp_path)

    service.update_item(
        item_id,
        title="物流异常主动通知",
        solution="增加物流节点超时检测和主动通知",
        owner="履约产品组",
        status="开发中",
        target_version="V1.2",
    )
    item = service.list_items()[0]

    assert item["title"] == "物流异常主动通知"
    assert item["owner"] == "履约产品组"
    assert item["status"] == "开发中"
    assert item["target_version"] == "V1.2"


@pytest.mark.parametrize(
    ("title", "solution", "status"),
    [("", "方案", "待评估"), ("标题", "", "待评估"), ("标题", "方案", "已取消")],
)
def test_update_rejects_invalid_fields(tmp_path, title, solution, status):
    _, service, item_id = seeded_service(tmp_path)

    with pytest.raises(ValueError):
        service.update_item(item_id, title, solution, "", status, "")


def test_archive_hides_item_and_restore_brings_it_back(tmp_path):
    _, service, item_id = seeded_service(tmp_path)

    service.archive_item(item_id)
    assert service.list_items() == []
    assert service.list_items(include_archived=True)[0]["archived_at"] is not None

    service.restore_item(item_id)
    assert service.list_items()[0]["id"] == item_id

