"""反馈问答 Agent 的单元测试 + 页面冒烟测试。

覆盖：
- 分词 / BM25 纯函数；
- 问题解析（分类、国家、月份、评分、影响度维度）；
- 检索命中、维度过滤、0 条时返回空；
- 拒答（库外指标、库内无主题词、过滤后 0 条）；
- 聚合数字与 SQL 直查一致；
- 引用只来自检索结果（不允许改写/外部文本）；
- 对比类两侧统计；
- 可选 DeepSeek 增强：严格 JSON 校验、失败回退模板；
- Streamlit 页面：空库诚实空状态、有数据时能出答案。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.agent import FeedbackRetriever, answer_question, bm25_scores, plan_query, tokenize
from src.agent.answer import validate_llm_payload
from src.db import connect
from src.repository import VoiceBoardRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RECORDS = (
    # id, 文本, 分类, 国家, 评分, 影响度, 商品品类, 日期
    ("T01", "包裹显示已签收但我没收到，联系快递也没用", "物流", "SG", 1, 5, "电子产品", "2026-10-31"),
    ("T02", "物流太慢，下单两周了还没到", "物流", "MY", 2, 4, "服饰", "2026-09-12"),
    ("T03", "快递把盒子压扁了，面霜漏出来", "物流", "TH", 1, 5, "美妆", "2026-10-25"),
    ("T04", "清关卡了十天，物流信息一直不更新", "物流", "ID", 2, 4, "家居", "2026-09-05"),
    ("T05", "配送员把包裹放在门口，结果丢了", "物流", "SG", 2, 4, "母婴", "2026-10-12"),
    ("T06", "用信用卡付款失败三次，换了支付方式才成功", "支付", "SG", 1, 5, "电子产品", "2026-10-30"),
    ("T07", "重复扣款了两笔，客服说会退但一周了没到账", "支付", "MY", 1, 5, "服饰", "2026-09-08"),
    ("T08", "PayPal 付款一直转圈，订单没生成", "支付", "TH", 2, 4, "美妆", "2026-10-15"),
    ("T09", "结算汇率和我看到的不一样", "支付", "ID", 2, 4, "家居", "2026-09-22"),
    ("T10", "衣服面料和图片差很多，起球严重", "商品质量", "MY", 2, 4, "服饰", "2026-09-25"),
    ("T11", "收到的面霜有异味，怀疑是假货", "商品质量", "TH", 1, 5, "美妆", "2026-10-20"),
    ("T12", "耳机左耳没声音，明显是质量问题", "商品质量", "SG", 1, 5, "电子产品", "2026-10-29"),
    ("T13", "椅子腿是裂的，做工粗糙", "商品质量", "ID", 2, 4, "家居", "2026-09-30"),
    ("T14", "客服一直机器人回复，转人工也没人接", "客服", "SG", 1, 5, "电子产品", "2026-10-27"),
    ("T15", "问客服退货地址，回复很慢", "客服", "MY", 2, 4, "服饰", "2026-09-10"),
    ("T16", "客服态度不耐烦，问题没解决就关对话", "客服", "TH", 2, 4, "美妆", "2026-10-02"),
    ("T17", "退货申请被拒绝了两次，理由每次都不一样", "退换货", "SG", 1, 5, "服饰", "2026-10-26"),
    ("T18", "退款拖了半个月还没到账，售后一直让等", "退换货", "US", 2, 4, "电子产品", "2026-09-14"),
    ("T19", "换货寄回去之后仓库说没收到", "退换货", "MY", 2, 4, "美妆", "2026-10-22"),
    ("T20", "搜索“耳机”出来的都是手机壳，搜不到想要的东西", "搜索推荐", "ID", 2, 3, "电子产品", "2026-09-26"),
    ("T21", "推荐的都是我买过的同类，几乎没有新东西", "搜索推荐", "SG", 3, 3, "服饰", "2026-10-10"),
    ("T22", "筛选按价格排序后结果乱七八糟", "搜索推荐", "US", 2, 3, "食品", "2026-09-24"),
)


def feedback_record(
    feedback_id: str,
    text: str,
    category: str,
    country: str,
    rating: int,
    impact: int,
    product: str,
    created: str,
) -> dict:
    return {
        "fingerprint": f"test-agent-{feedback_id}",
        "feedback_id": feedback_id,
        "feedback_text": text,
        "country": country,
        "user_type": "新用户",
        "product_category": product,
        "rating": rating,
        "created_at": created,
        "category": category,
        "impact_level": impact,
        "classification_source": "rule",
        "confidence": 0.9,
        "classification_reason": "测试语料固定标签",
    }


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "voiceboard.db"
    repository = VoiceBoardRepository(path)
    repository.initialize()
    repository.import_feedback(
        "agent-test.csv",
        "rule",
        len(RECORDS),
        [
            feedback_record(*record)
            for record in RECORDS
        ],
    )
    return path


# ---------------------------------------------------------------------------
# 分词与打分
# ---------------------------------------------------------------------------


def test_tokenize_uses_chinese_bigrams_and_drops_stopwords():
    tokens = tokenize("物流太慢")
    assert "物流" in tokens
    assert "流太" in tokens
    assert "太慢" in tokens

    question_tokens = tokenize("为什么物流有多少条反馈")
    assert "为什" not in question_tokens
    assert "什么" not in question_tokens
    assert "反馈" not in question_tokens
    assert "多少" not in question_tokens
    assert "物流" in question_tokens


def test_tokenize_keeps_english_words_and_strips_punctuation():
    tokens = tokenize("PayPal 付款一直转圈")
    assert "paypal" in tokens
    assert "付款" in tokens


def test_bm25_scores_the_matching_document_higher():
    documents = [tokenize("包裹丢了而且快递不回复"), tokenize("支付失败订单没有生成")]
    scores = bm25_scores(tokenize("包裹"), documents)

    assert scores[0] > scores[1]
    assert scores[1] == 0.0


# ---------------------------------------------------------------------------
# 问题解析
# ---------------------------------------------------------------------------


def test_plan_query_extracts_dimension_filters():
    plan = plan_query("2026年10月新加坡物流差评有哪些？")

    assert plan.filters["category"] == "物流"
    assert plan.filters["country"] == "SG"
    assert plan.filters["rating_max"] == 2
    assert plan.filters["date_from"] == "2026-10-01"
    assert plan.filters["date_to_exclusive"] == "2026-11-01"


def test_plan_query_keeps_multiple_categories_for_comparison():
    plan = plan_query("物流和支付哪个分类的反馈更多？")

    assert plan.categories == ("物流", "支付")
    assert "category" not in plan.filters


def test_plan_query_recognizes_chinese_country_names_and_uppercase_codes():
    plan = plan_query("印度用户对物流的反馈有哪些？")
    assert plan.filters["country"] == "IN"
    assert plan.filters["category"] == "物流"

    code_plan = plan_query("SG 用户对支付的反馈有哪些？")
    assert code_plan.filters["country"] == "SG"
    assert code_plan.filters["category"] == "支付"

    # 英文句子里的 in/id 之类的单词不能被误判成国家码
    english_plan = plan_query("delivery delay in the app")
    assert english_plan.countries == ()


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


def test_retrieval_returns_evidence_with_required_metadata(database):
    retriever = FeedbackRetriever(database)
    # “包裹”命中物流维度，因此只在该分类内检索；这是刻意的维度过滤行为。
    result = retriever.search("包裹一直没收到", top_k=5)
    with connect(database) as connection:
        expected_count = connection.execute(
            "SELECT COUNT(*) AS count FROM feedback WHERE category = ?", ("物流",)
        ).fetchone()["count"]

    assert result.hits
    top = result.hits[0]
    assert top.feedback_id == "T01"
    assert top.category == "物流"
    assert top.country == "SG"
    assert top.rating == 1
    assert top.feedback_text
    assert top.impact_level == 5
    assert top.matched_terms
    assert result.plan.filters["category"] == "物流"
    assert result.aggregate.count == expected_count


def test_retrieval_applies_dimension_filters(database):
    retriever = FeedbackRetriever(database)
    result = retriever.search("新加坡用户对客服的抱怨是什么？", top_k=5)

    assert result.plan.filters["category"] == "客服"
    assert result.plan.filters["country"] == "SG"
    assert result.aggregate.count == 1
    assert [hit.feedback_id for hit in result.hits] == ["T14"]
    assert all(hit.country == "SG" and hit.category == "客服" for hit in result.hits)


def test_retrieval_returns_empty_when_filter_has_no_rows(database):
    retriever = FeedbackRetriever(database)
    result = retriever.search("巴西市场用户对物流的抱怨是什么？")

    assert result.plan.filters["country"] == "BR"
    assert result.aggregate.count == 0
    assert result.hits == ()
    assert result.corpus_scored == 0


def test_retrieval_resolves_country_filter_to_actual_db_value(database):
    """真实数据的国家字段可能是中文名（如“印度”），问题解析出的是 canonical code（IN）。"""
    retriever = FeedbackRetriever(database)
    missing = retriever.search("印度用户对物流的反馈有哪些？")
    assert missing.aggregate.count == 0
    assert any("没有国家" in note for note in missing.notes)

    repository = VoiceBoardRepository(database)
    repository.import_feedback(
        "extra-country.csv",
        "rule",
        1,
        [
            feedback_record(
                "T91",
                "印度这边包裹配送很慢，等了两周",
                "物流",
                "印度",
                2,
                4,
                "服饰",
                "2026-10-15",
            )
        ],
    )
    resolved = retriever.search("印度用户对物流的反馈有哪些？")
    assert resolved.plan.filters["country"] == "印度"
    assert resolved.aggregate.count == 1
    assert resolved.hits[0].country == "印度"
    assert any("校正" in note for note in resolved.notes)


def test_retrieval_maps_cross_border_market_to_global_not_single_country(database):
    """真实数据里“多国（跨境）”是市场标签，应映射 GLOBAL 专列，而不是并入某个国家。"""
    repository = VoiceBoardRepository(database)
    repository.import_feedback(
        "extra-global.csv",
        "rule",
        1,
        [
            feedback_record(
                "T92",
                "包裹在多国转运时丢了，跨境物流很慢",
                "物流",
                "多国（跨境）",
                1,
                5,
                "美妆",
                "2026-10-16",
            )
        ],
    )
    plan = plan_query("多国市场用户的物流反馈有哪些？")
    assert plan.filters["country"] == "GLOBAL"

    result = FeedbackRetriever(database).search("多国市场用户的物流反馈有哪些？")
    assert result.plan.filters["country"] == "多国（跨境）"
    assert result.aggregate.count == 1
    assert result.hits[0].country == "多国（跨境）"


# ---------------------------------------------------------------------------
# 拒答
# ---------------------------------------------------------------------------


def test_answer_refuses_out_of_scope_business_metrics(database):
    answer = answer_question("我们上季度的营收和利润是多少？", database)

    assert answer.refused is True
    assert "当前库内没有足够证据" in answer.text
    assert answer.evidence == ()
    assert answer.citations == ()


def test_answer_refuses_topic_absent_from_library(database):
    answer = answer_question("用户对元宇宙虚拟试衣功能的反馈如何？", database)

    assert answer.refused is True
    assert "当前库内没有足够证据" in answer.text
    assert "元宇宙" not in "".join(hit.feedback_text for hit in answer.evidence)


def test_answer_refuses_when_filter_yields_zero_rows(database):
    answer = answer_question("巴西市场用户对物流有什么抱怨？", database)

    assert answer.refused is True
    assert "0 条" in answer.text


def test_answer_refuses_empty_question(database):
    answer = answer_question("   ", database)

    assert answer.refused is True
    assert "问题为空" in answer.text


# ---------------------------------------------------------------------------
# 聚合与引用
# ---------------------------------------------------------------------------


def test_aggregate_answer_count_matches_direct_sql(database):
    answer = answer_question("物流类反馈一共有多少条？", database)

    with connect(database) as connection:
        expected = connection.execute(
            "SELECT COUNT(*) AS count FROM feedback WHERE category = ?", ("物流",)
        ).fetchone()["count"]
    assert answer.refused is False
    assert str(expected) in answer.text
    assert answer.aggregate.count == expected
    assert answer.citations


def test_time_filter_aggregate_matches_direct_sql(database):
    answer = answer_question("2026年10月的反馈一共有多少条？", database)

    with connect(database) as connection:
        expected = connection.execute(
            "SELECT COUNT(*) AS count FROM feedback WHERE created_at >= ? AND created_at < ?",
            ("2026-10-01", "2026-11-01"),
        ).fetchone()["count"]
    assert answer.aggregate.count == expected
    assert answer.refused is False


def test_citations_only_come_from_retrieval_evidence(database):
    questions = (
        "物流类反馈一共有多少条？平均影响程度是多少？",
        "用户抱怨物流慢的反馈有哪些？",
        "物流和支付哪个分类的反馈更多？",
    )
    for question in questions:
        answer = answer_question(question, database)
        assert answer.refused is False, question
        evidence_ids = {item.row_id for item in answer.evidence}
        evidence_text = {item.row_id: item.feedback_text for item in answer.evidence}
        assert answer.citations, question
        for citation in answer.citations:
            assert citation.row_id in evidence_ids
            # 引用必须是检索结果原文，不允许改写或引入外部文本
            assert citation.feedback_text == evidence_text[citation.row_id]


def test_comparison_answer_reports_both_sides_from_sql(database):
    answer = answer_question("物流和支付哪个分类的反馈更多？", database)

    assert answer.intent == "comparison"
    assert answer.refused is False
    assert len(answer.sides) == 2
    labels = {side.label for side in answer.sides}
    assert labels == {"物流", "支付"}
    with connect(database) as connection:
        counts = {
            row["category"]: row["count"]
            for row in connection.execute(
                "SELECT category, COUNT(*) AS count FROM feedback "
                "WHERE category IN ('物流', '支付') GROUP BY category"
            ).fetchall()
        }
    side_counts = {side.label: side.aggregate.count for side in answer.sides}
    assert side_counts == counts
    assert len(answer.citations) == 2


# ---------------------------------------------------------------------------
# 可选 DeepSeek 增强
# ---------------------------------------------------------------------------


def test_validate_llm_payload_accepts_valid_and_rejects_invalid():
    allowed = ["T01", "T02"]
    valid = json.dumps(
        {"answer": "物流问题最多", "cited_ids": ["T01"], "refused": False, "reason": ""}
    )
    assert validate_llm_payload(valid, allowed) == {
        "answer": "物流问题最多",
        "cited_ids": ["T01"],
        "refused": False,
        "reason": "",
    }

    unknown_citation = json.dumps(
        {"answer": "编造", "cited_ids": ["T99"], "refused": False}
    )
    assert validate_llm_payload(unknown_citation, allowed) is None
    assert validate_llm_payload("这不是 JSON", allowed) is None
    assert validate_llm_payload(json.dumps({"answer": ""}), allowed) is None


def test_llm_failure_falls_back_to_template(database, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.agent.answer._call_deepseek", boom)
    answer = answer_question(
        "物流类反馈一共有多少条？",
        database,
        llm=True,
        api_key="fake-key",
    )

    assert answer.mode == "template"
    assert answer.refused is False
    assert "共有" in answer.text


def test_llm_success_keeps_citations_inside_retrieval(database, monkeypatch):
    template_answer = answer_question("用户抱怨物流慢的反馈有哪些？", database)
    allowed = [item.display_id for item in template_answer.evidence]
    assert allowed

    def fake_call(*args, **kwargs):
        return json.dumps(
            {
                "answer": "用户主要抱怨物流慢。",
                "cited_ids": [allowed[0]],
                "refused": False,
                "reason": "",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("src.agent.answer._call_deepseek", fake_call)
    answer = answer_question(
        "用户抱怨物流慢的反馈有哪些？",
        database,
        llm=True,
        api_key="fake-key",
    )

    assert answer.mode == "template+deepseek"
    assert answer.cited_ids == (allowed[0],)
    assert all(citation.display_id in allowed for citation in answer.citations)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


def test_question_page_has_an_honest_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(tmp_path / "voiceboard.db"))

    app = AppTest.from_file(str(PROJECT_ROOT / "pages" / "7_反馈问答.py"))
    app.run(timeout=15)

    assert not app.exception
    assert app.title[0].value == "反馈问答"
    assert any("还没有反馈" in info.value for info in app.info)


def test_question_page_answers_from_sqlite(database, monkeypatch):
    monkeypatch.setenv("VOICEBOARD_DB_PATH", str(database))

    app = AppTest.from_file(str(PROJECT_ROOT / "pages" / "7_反馈问答.py"))
    app.session_state["agent_active_question"] = "物流类反馈一共有多少条？"
    app.run(timeout=20)

    assert not app.exception
    page_text = "\n".join(element.value for element in app.markdown)
    assert "条反馈" in page_text
    assert app.dataframe
    assert "\ufffd" not in page_text
