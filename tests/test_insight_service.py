from src.repository import VoiceBoardRepository
from src.services.insight_service import InsightService


def record(category, impact, text):
    return {
        "category": category,
        "impact_level": impact,
        "feedback_text": text,
        "country": "SG",
        "user_type": "新用户",
        "product_category": "电子产品",
    }


def test_insights_include_rank_evidence_and_editable_product_solution(tmp_path):
    repository = VoiceBoardRepository(tmp_path / "voiceboard.db")
    repository.initialize()
    service = InsightService(repository)
    records = [
        record("物流", 5, "包裹丢了"),
        record("物流", 4, "配送很慢"),
        record("支付", 3, "付款失败"),
    ]

    insights = service.build_insights(records, {"country": "SG"})

    assert insights[0].rank == 1
    assert insights[0].category == "物流"
    assert insights[0].priority_score == 9.0
    assert insights[0].evidence == ["包裹丢了", "配送很慢"]
    assert "物流" in insights[0].solution


def test_creating_a_roadmap_card_persists_snapshot_and_is_idempotent(tmp_path):
    repository = VoiceBoardRepository(tmp_path / "voiceboard.db")
    repository.initialize()
    service = InsightService(repository)
    insight = service.build_insights(
        [record("支付", 5, "重复扣款")], {"country": "SG", "user_type": "新用户"}
    )[0]

    first = service.create_roadmap_item(
        insight,
        solution="增加支付失败原因提示和备用支付方式",
        owner="支付产品组",
        target_version="V1.1",
    )
    second = service.create_roadmap_item(
        insight,
        solution="不会覆盖已有卡片",
        owner="其他人",
        target_version="V2.0",
    )
    items = repository.list_roadmap_items()

    assert first.created is True
    assert second.created is False
    assert first.item_id == second.item_id
    assert len(items) == 1
    assert items[0]["solution"] == "增加支付失败原因提示和备用支付方式"
    assert '"country": "SG"' in items[0]["filter_snapshot"]

