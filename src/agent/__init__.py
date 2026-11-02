"""反馈问答 / 归因 Agent 的最小可用实现。

设计边界（详见 docs/agent-scope.md）：
- 检索：纯标准库实现的关键词 + 中文 bigram + BM25 打分 + 维度过滤，不引入向量库/embedding。
- 回答：默认确定性模板（聚合统计 + 原文引用），证据不足时显式拒答。
- 可选 DeepSeek 增强：默认关闭；开启时必须严格 JSON 且引用只能来自检索结果，失败回退模板。
"""

from src.agent.answer import (
    Answer,
    CategorySide,
    answer_question,
    detect_intent,
    validate_llm_payload,
)
from src.agent.retrieval import (
    AggregateStats,
    Evidence,
    FeedbackRetriever,
    QueryPlan,
    RetrievalResult,
    bm25_scores,
    plan_query,
    tokenize,
)

__all__ = [
    "AggregateStats",
    "Answer",
    "CategorySide",
    "Evidence",
    "FeedbackRetriever",
    "QueryPlan",
    "RetrievalResult",
    "answer_question",
    "bm25_scores",
    "detect_intent",
    "plan_query",
    "tokenize",
    "validate_llm_payload",
]
