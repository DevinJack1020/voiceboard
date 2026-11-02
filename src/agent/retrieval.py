"""基于 SQLite feedback 表的确定性检索层。

实现范围（刻意保持最小）：
1. 问题解析：识别分类 / 国家 / 商品品类 / 评分 / 影响度 / 月份等维度，转成 SQL 过滤条件；
2. 文本匹配：中文按字符 bigram、英文按单词切分，停用词过滤；
3. 打分：BM25（k1=1.5, b=0.75），只在过滤后的候选集内计算 df / idf / avgdl；
4. 输出：带 feedback id、原文、分类、国家、评分、影响度、命中词的证据列表。

已知边界：
- 纯字面匹配，不做同义词扩展和跨语言语义检索（"钱退不回来" 匹配不到 "退款拖了半个月"）；
- 中文 bigram 会跨越词边界产生噪声 token，靠停用词与 BM25 的 idf 抑制，但不彻底；
- 证据不足（过滤后 0 条 / 主题词在库内不存在）时返回空 hits，由 answer 层显式拒答，绝不补全。
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from src.db import connect


DEFAULT_TOP_K = 5
DEFAULT_MAX_DOCS = 2_000
BM25_K1 = 1.5
BM25_B = 0.75
MAX_IDF = 6.0

BUSINESS_CATEGORIES = ("物流", "支付", "商品质量", "搜索推荐", "客服", "退换货")
ALL_CATEGORIES = BUSINESS_CATEGORIES + ("待确认",)

# 问题里出现这些词时，认为用户在问某个分类；用于维度过滤，不是分类器。
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "物流": ("物流", "快递", "配送", "包裹", "发货", "到货", "运输", "签收", "清关", "物流时效"),
    "支付": ("支付", "付款", "扣款", "结算", "信用卡", "银行卡", "paypal", "钱包"),
    "商品质量": ("商品质量", "质量", "破损", "假货", "瑕疵", "次品", "做工", "面料", "材质"),
    "搜索推荐": ("搜索推荐", "搜索", "推荐", "筛选", "排序", "搜不到", "关键词"),
    "客服": ("客服", "人工客服", "人工回复", "服务态度"),
    "退换货": ("退换货", "退货", "换货", "退款", "售后"),
}

COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "SG": ("新加坡", "singapore", "狮城"),
    "MY": ("马来西亚", "malaysia"),
    "TH": ("泰国", "thailand"),
    "ID": ("印尼", "印度尼西亚", "indonesia"),
    "US": ("美国", "usa", "united states", "america"),
    "PH": ("菲律宾", "philippines"),
    "VN": ("越南", "vietnam"),
    "JP": ("日本", "japan"),
    "KR": ("韩国", "korea"),
    "BR": ("巴西", "brazil"),
    "DE": ("德国", "germany"),
    "GB": ("英国", "britain"),
    "MX": ("墨西哥", "mexico"),
    "SA": ("沙特", "saudi"),
    # 真实数据里的国家取值可能是中文名（如 印度/美国/中国），
    # 这些别名用于"问题→canonical code→库内实际取值"的校正，见 FeedbackRetriever.search。
    "CN": ("中国", "china"),
    "IN": ("印度", "india"),
    # 真实数据里的"多国（跨境）"是按 App 主要市场推断的聚合市场标签，不是单一国家；
    # 映射为 GLOBAL 专列，避免把跨境样本并入某个国家（也避免"美国=0 条"之类误拒）。
    "GLOBAL": ("多国", "多国（跨境）"),
}
# 国家码只匹配"全大写、独立出现"的写法（SG/IN/US…），避免英文句子里的 in/id/my 被误判。
COUNTRY_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(sorted(COUNTRY_ALIASES, key=len, reverse=True))
    + r")(?![A-Za-z])"
)

PRODUCT_CATEGORY_ALIASES = (
    "电子产品",
    "服饰",
    "美妆",
    "家居",
    "母婴",
    "食品",
    "数码",
    "鞋服",
    "保健",
    "箱包",
)

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
LATIN_TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
MONTH_PATTERN = re.compile(r"(20\d{2})\s*(?:年|[-/])\s*(\d{1,2})\s*月?")

STOPWORDS = frozenset(
    {
        # 中文疑问/功能词（bigram 形式）
        "这个",
        "那个",
        "这些",
        "那些",
        "什么",
        "怎么",
        "怎样",
        "为什",
        "如何",
        "哪些",
        "哪个",
        "多少",
        "几个",
        "是否",
        "没有",
        "有没",
        "可以",
        "我们",
        "你们",
        "他们",
        "一下",
        "请问",
        "目前",
        "最近",
        "现在",
        "已经",
        "还是",
        "或者",
        "以及",
        "还有",
        "并且",
        "但是",
        "因为",
        "所以",
        "如果",
        "一个",
        "一些",
        "这样",
        "那样",
        "这种",
        "那种",
        "有哪",
        "主要",
        "问题",
        "反馈",
        "用户",
        "评论",
        "评价",
        "内容",
        "具体",
        "相关",
        "情况",
        "方面",
        "告诉",
        "介绍",
        "说明",
        "解释",
        "分析",
        "出现",
        "存在",
        "觉得",
        "感觉",
        "认为",
        "希望",
        "最多",
        "最高",
        "最低",
        "更多",
        "更高",
        "对比",
        "比较",
        "相比",
        "差距",
        "分别",
        "一共",
        "总共",
        "合计",
        "数量",
        "总量",
        "占比",
        "比例",
        "平均",
        "影响",
        "程度",
        "排名",
        "案例",
        "证据",
        "原话",
        "原文",
        "例子",
        "举例",
        "摘录",
        "引用",
    }
    | {
        # 英文停用词（真实数据里可能出现中英混排）
        "the",
        "and",
        "is",
        "are",
        "was",
        "were",
        "a",
        "an",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "it",
        "this",
        "that",
        "i",
        "my",
        "me",
        "we",
        "you",
        "they",
        "but",
        "not",
        "no",
        "so",
        "if",
        "at",
        "by",
        "from",
        "as",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "can",
        "could",
        "would",
        "should",
        "will",
        "just",
        "very",
        "really",
        "too",
        "also",
        "than",
        "then",
        "there",
        "their",
        "our",
        "your",
        "its",
        "about",
        "after",
        "before",
        "over",
        "under",
        "again",
        "more",
        "most",
        "some",
        "any",
        "all",
        "feedback",
        "app",
    }
)


# ---------------------------------------------------------------------------
# 分词与打分（纯函数，便于单测）
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """中文按 bigram、英文按单词切分，并去掉停用词。

    中文单字成段时保留单字（如 "慢"），否则只保留相邻二字 bigram。
    """
    if not text:
        return []
    lowered = text.lower()
    tokens: list[str] = []
    for run in CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    tokens.extend(LATIN_TOKEN.findall(lowered))
    return [token for token in tokens if token not in STOPWORDS]


def bm25_scores(
    query_tokens: Sequence[str],
    documents: Sequence[Sequence[str]],
) -> list[float]:
    """对 documents（已分词）计算 BM25 分数，返回与 documents 等长的分数列表。"""
    if not documents or not query_tokens:
        return [0.0 for _ in documents]
    document_count = len(documents)
    frequencies = [Counter(document) for document in documents]
    document_frequency = Counter()
    for tokens in documents:
        for token in set(tokens):
            document_frequency[token] += 1
    average_length = sum(len(tokens) for tokens in documents) / document_count
    average_length = average_length or 1.0
    weighted_query = Counter(query_tokens)
    scores: list[float] = []
    for tokens, frequency in zip(documents, frequencies):
        length = len(tokens) or 1.0
        score = 0.0
        for token, query_weight in weighted_query.items():
            term_frequency = frequency.get(token, 0)
            if not term_frequency:
                continue
            document_term_count = document_frequency[token]
            idf = math.log(
                1.0
                + (document_count - document_term_count + 0.5)
                / (document_term_count + 0.5)
            )
            idf = min(idf, MAX_IDF)
            denominator = term_frequency + BM25_K1 * (
                1.0 - BM25_B + BM25_B * length / average_length
            )
            score += query_weight * idf * term_frequency * (BM25_K1 + 1.0) / denominator
        scores.append(round(score, 6))
    return scores


# ---------------------------------------------------------------------------
# 问题解析
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryPlan:
    """一次检索的结构化口径，便于页面展示"我到底按什么在查"。"""

    question: str
    filters: Mapping[str, object]
    categories: tuple[str, ...]
    countries: tuple[str, ...]
    query_tokens: tuple[str, ...]
    free_tokens: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def filter_summary(self) -> str:
        labels = []
        if self.filters.get("category"):
            labels.append(f"分类={self.filters['category']}")
        if self.filters.get("country"):
            labels.append(f"国家={self.filters['country']}")
        if self.filters.get("product_category"):
            labels.append(f"商品品类={self.filters['product_category']}")
        if self.filters.get("user_type"):
            labels.append(f"用户类型={self.filters['user_type']}")
        if self.filters.get("rating_min") is not None:
            labels.append(f"评分≥{self.filters['rating_min']}")
        if self.filters.get("rating_max") is not None:
            labels.append(f"评分≤{self.filters['rating_max']}")
        if self.filters.get("impact_min") is not None:
            labels.append(f"影响度≥{self.filters['impact_min']}")
        if self.filters.get("impact_max") is not None:
            labels.append(f"影响度≤{self.filters['impact_max']}")
        if self.filters.get("date_from"):
            labels.append(f"起始日期={self.filters['date_from']}")
        if self.filters.get("date_to_exclusive"):
            labels.append(f"截止日期<{self.filters['date_to_exclusive']}")
        return "；".join(labels) if labels else "全部反馈（无维度过滤）"


def _match_alias(text: str, alias: str) -> int:
    """返回别名在问题中首次出现的下标，找不到返回 -1。"""
    lowered = text.lower()
    if alias.isascii():
        pattern = re.compile(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])")
        found = pattern.search(lowered)
        return found.start() if found else -1
    return lowered.find(alias)


def _detect_dimension(
    text: str,
    alias_map: Mapping[str, tuple[str, ...]],
) -> list[tuple[int, str]]:
    found: dict[str, int] = {}
    for canonical, aliases in alias_map.items():
        positions = [_match_alias(text, alias) for alias in aliases]
        positions = [position for position in positions if position >= 0]
        if positions:
            found[canonical] = min(positions)
    return sorted(((position, name) for name, position in found.items()), key=lambda item: item[0])


def _month_filters(question: str) -> tuple[dict[str, object], tuple[str, ...]]:
    match = MONTH_PATTERN.search(question)
    if not match:
        return {}, ()
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return {}, (f"无法识别的月份：{match.group(0)}",)
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return (
        {"date_from": start.isoformat(), "date_to_exclusive": end.isoformat()},
        (f"识别到时间维度：{year}-{month:02d}",),
    )


def _rating_and_impact_filters(question: str) -> tuple[dict[str, object], list[str]]:
    filters: dict[str, object] = {}
    notes: list[str] = []
    chinese_stars = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    star_match = re.search(r"(?<![0-9])([1-5])\s*星", question)
    if star_match:
        filters["rating_min"] = filters["rating_max"] = int(star_match.group(1))
        notes.append(f"识别到评分为 {star_match.group(1)} 星")
    else:
        for word, value in chinese_stars.items():
            if f"{word}星" in question:
                filters["rating_min"] = filters["rating_max"] = value
                notes.append(f"识别到评分为 {word}星")
                break
    if any(word in question for word in ("差评", "低评分", "评分低", "低分")):
        filters.setdefault("rating_max", 2)
        notes.append("识别到低评分意图：评分≤2")
    if any(word in question for word in ("好评", "高评分", "评分高")):
        filters.setdefault("rating_min", 4)
        notes.append("识别到高评分意图：评分≥4")
    if any(word in question for word in ("高影响", "影响大", "严重影响", "严重")):
        filters.setdefault("impact_min", 4)
        notes.append("识别到高影响意图：影响度≥4")
    if any(word in question for word in ("低影响", "影响小")):
        filters.setdefault("impact_max", 2)
        notes.append("识别到低影响意图：影响度≤2")
    return filters, notes


def plan_query(question: str) -> QueryPlan:
    """把自然语言问题变成检索口径：维度过滤 + 词面 token。"""
    text = question.strip()
    notes: list[str] = []

    category_matches = _detect_dimension(text, CATEGORY_ALIASES)
    categories = tuple(name for _, name in category_matches)
    country_matches = _detect_dimension(text, COUNTRY_ALIASES)
    countries = [name for _, name in country_matches]
    # 英文国家码再扫一遍（只认全大写、独立出现的 SG/MY/IN…，避免 in/id/my 误判）
    for code_match in COUNTRY_CODE_PATTERN.finditer(text):
        code = code_match.group(1).upper()
        if code not in countries:
            countries.append(code)
    countries = tuple(countries)

    filters: dict[str, object] = {}
    if len(categories) == 1:
        filters["category"] = categories[0]
    elif len(categories) > 1:
        notes.append("问题命中多个分类，未按分类过滤（对比类问题由回答层分别统计）")
    if len(countries) == 1:
        filters["country"] = countries[0]
    elif len(countries) > 1:
        notes.append("问题命中多个国家，未按国家过滤（对比类问题由回答层分别统计）")

    product_matches = [
        alias
        for alias in PRODUCT_CATEGORY_ALIASES
        if alias in text
    ]
    if len(product_matches) == 1:
        filters["product_category"] = product_matches[0]

    month_filters, month_notes = _month_filters(text)
    filters.update(month_filters)
    notes.extend(month_notes)
    rating_filters, rating_notes = _rating_and_impact_filters(text)
    filters.update(rating_filters)
    notes.extend(rating_notes)

    query_tokens = tuple(dict.fromkeys(tokenize(text)))
    filter_values = " ".join(str(value) for value in filters.values())
    filter_tokens = set(tokenize(filter_values))
    free_tokens = tuple(
        token for token in query_tokens if token not in filter_tokens
    )
    return QueryPlan(
        question=text,
        filters=filters,
        categories=categories,
        countries=countries,
        query_tokens=query_tokens,
        free_tokens=free_tokens,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# 检索结果数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """一条可引用的反馈证据。"""

    row_id: int
    feedback_id: str | None
    feedback_text: str
    category: str
    country: str
    user_type: str
    product_category: str
    rating: int
    impact_level: int
    created_at: str
    score: float
    matched_terms: tuple[str, ...] = ()

    @property
    def display_id(self) -> str:
        return self.feedback_id or f"#{self.row_id}"

    @property
    def metadata_text(self) -> str:
        return (
            f"{self.category} / {self.country} / {self.rating} 星 / "
            f"影响 {self.impact_level} / {self.created_at}"
        )


@dataclass(frozen=True)
class AggregateStats:
    """过滤范围内的全量聚合统计（不是 top-k 统计）。"""

    count: int
    average_impact: float | None
    average_rating: float | None
    negative_rating_share: float | None
    by_category: tuple[tuple[str, int], ...]
    by_country: tuple[tuple[str, int], ...]

    def category_count(self, category: str) -> int:
        for name, value in self.by_category:
            if name == category:
                return value
        return 0


@dataclass(frozen=True)
class RetrievalResult:
    question: str
    plan: QueryPlan
    hits: tuple[Evidence, ...]
    aggregate: AggregateStats
    corpus_scored: int
    top_score: float
    matched_terms: tuple[str, ...]
    free_matched_terms: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def hit_ids(self) -> tuple[str, ...]:
        return tuple(hit.display_id for hit in self.hits)

    @property
    def has_filters(self) -> bool:
        return bool(self.plan.filters)


# ---------------------------------------------------------------------------
# 检索器
# ---------------------------------------------------------------------------


FILTER_COLUMNS = ("country", "user_type", "product_category", "category")


def _build_where(filters: Mapping[str, object]) -> tuple[str, list[object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    for column in FILTER_COLUMNS:
        value = filters.get(column)
        if value:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    for column in ("rating", "impact_level"):
        minimum = filters.get(f"{column}_min")
        maximum = filters.get(f"{column}_max")
        if minimum is not None:
            clauses.append(f"{column} >= ?")
            parameters.append(minimum)
        if maximum is not None:
            clauses.append(f"{column} <= ?")
            parameters.append(maximum)
    if filters.get("date_from"):
        clauses.append("created_at >= ?")
        parameters.append(filters["date_from"])
    if filters.get("date_to_exclusive"):
        clauses.append("created_at < ?")
        parameters.append(filters["date_to_exclusive"])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, parameters


def _aggregate(
    connection: sqlite3.Connection,
    filters: Mapping[str, object],
) -> AggregateStats:
    where, parameters = _build_where(filters)
    summary = connection.execute(
        f"""
        SELECT COUNT(*) AS count,
               AVG(impact_level) AS average_impact,
               AVG(rating) AS average_rating,
               SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS negative
        FROM feedback{where}
        """,
        parameters,
    ).fetchone()
    count = int(summary["count"] or 0)
    negative = int(summary["negative"] or 0)
    grouped = connection.execute(
        f"""
        SELECT category, COUNT(*) AS count
        FROM feedback{where}
        GROUP BY category
        ORDER BY count DESC, category ASC
        """,
        parameters,
    ).fetchall()
    countries = connection.execute(
        f"""
        SELECT country, COUNT(*) AS count
        FROM feedback{where}
        GROUP BY country
        ORDER BY count DESC, country ASC
        """,
        parameters,
    ).fetchall()
    return AggregateStats(
        count=count,
        average_impact=(
            round(float(summary["average_impact"]), 2)
            if summary["average_impact"] is not None
            else None
        ),
        average_rating=(
            round(float(summary["average_rating"]), 2)
            if summary["average_rating"] is not None
            else None
        ),
        negative_rating_share=(round(negative / count, 4) if count else None),
        by_category=tuple((str(row["category"]), int(row["count"])) for row in grouped),
        by_country=tuple((str(row["country"]), int(row["count"])) for row in countries),
    )


def _to_evidence(row: sqlite3.Row, score: float, matched: list[str]) -> Evidence:
    return Evidence(
        row_id=int(row["id"]),
        feedback_id=row["feedback_id"],
        feedback_text=str(row["feedback_text"]),
        category=str(row["category"]),
        country=str(row["country"]),
        user_type=str(row["user_type"]),
        product_category=str(row["product_category"]),
        rating=int(row["rating"]),
        impact_level=int(row["impact_level"]),
        created_at=str(row["created_at"]),
        score=score,
        matched_terms=tuple(dict.fromkeys(matched)),
    )


def _date_ordinal(value: str) -> int:
    try:
        return date.fromisoformat(str(value)[:10]).toordinal()
    except ValueError:
        return 0


class FeedbackRetriever:
    """在一个 SQLite 库上做"过滤 + BM25"检索。不建索引、不缓存，数据量小可接受。"""

    def __init__(
        self,
        database: Path | str,
        *,
        max_docs: int = DEFAULT_MAX_DOCS,
    ):
        self.database = Path(database)
        self.max_docs = max(1, int(max_docs))

    def search(
        self,
        question: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        extra_filters: Mapping[str, object] | None = None,
    ) -> RetrievalResult:
        plan = plan_query(question)
        filters: dict[str, object] = dict(plan.filters)
        notes = list(plan.notes)
        if extra_filters:
            for key, value in extra_filters.items():
                if value is not None:
                    filters[key] = value
        with connect(self.database) as connection:
            product_category = filters.get("product_category")
            if product_category:
                actual = {
                    str(row["product_category"])
                    for row in connection.execute(
                        "SELECT DISTINCT product_category FROM feedback"
                    ).fetchall()
                }
                if str(product_category) not in actual:
                    replacement = next(
                        (
                            value
                            for value in sorted(actual)
                            if str(product_category) in value or value in str(product_category)
                        ),
                        None,
                    )
                    if replacement:
                        filters["product_category"] = replacement
                        notes.append(
                            f"商品品类按库内实际取值校正：{product_category} → {replacement}"
                        )
                    else:
                        notes.append(
                            f"库内没有商品品类「{product_category}」（过滤后应为 0 条，"
                            "不会用其他品类替代）"
                        )
            country = filters.get("country")
            if country:
                # 真实数据里国家可能是中文名（印度/美国/中国…），问题解析出的是
                # canonical code（IN/US/CN…）；这里按"库内实际取值"做一次校正。
                actual_countries = {
                    str(row["country"])
                    for row in connection.execute(
                        "SELECT DISTINCT country FROM feedback"
                    ).fetchall()
                }
                wanted = str(country)
                if wanted not in actual_countries:
                    aliases = COUNTRY_ALIASES.get(wanted, ())
                    replacement = next(
                        (
                            value
                            for value in sorted(actual_countries)
                            if any(_match_alias(value, alias) >= 0 for alias in aliases)
                        ),
                        None,
                    )
                    if replacement:
                        filters["country"] = replacement
                        notes.append(
                            f"国家按库内实际取值校正：{wanted} → {replacement}"
                        )
                    else:
                        notes.append(
                            f"库内没有国家「{wanted}」（过滤后应为 0 条，不会用其他市场替代）"
                        )
            where, parameters = _build_where(filters)
            aggregate = _aggregate(connection, filters)
            rows = connection.execute(
                f"""
                SELECT id, feedback_id, feedback_text, country, user_type,
                       product_category, rating, created_at, category, impact_level
                FROM feedback{where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*parameters, self.max_docs),
            ).fetchall()
        if dict(plan.filters) != filters:
            # 维度过滤按库内实际取值校正后，把修正结果同步回口径展示。
            plan = replace(plan, filters=dict(filters), notes=tuple(notes))
        documents = [tokenize(str(row["feedback_text"])) for row in rows]
        scores = bm25_scores(list(plan.query_tokens), documents)
        document_frequency: Counter[str] = Counter()
        for tokens in documents:
            document_frequency.update(set(tokens))
        matched_terms = tuple(
            token
            for token in dict.fromkeys(plan.query_tokens)
            if document_frequency.get(token, 0) > 0
        )
        free_terms = set(plan.free_tokens)
        free_matched_terms = tuple(
            token for token in matched_terms if token in free_terms
        )
        evidence: list[Evidence] = []
        for row, tokens, score in zip(rows, documents, scores):
            token_set = set(tokens)
            matched = [token for token in plan.query_tokens if token in token_set]
            evidence.append(_to_evidence(row, score, matched))
        evidence.sort(
            key=lambda item: (
                -item.score,
                -item.impact_level,
                item.rating,
                -_date_ordinal(item.created_at),
                item.row_id,
            )
        )
        hits = tuple(evidence[: max(1, min(top_k, 50))])
        return RetrievalResult(
            question=plan.question,
            plan=plan,
            hits=hits,
            aggregate=aggregate,
            corpus_scored=len(rows),
            top_score=hits[0].score if hits else 0.0,
            matched_terms=matched_terms,
            free_matched_terms=free_matched_terms,
            notes=tuple(notes),
        )
