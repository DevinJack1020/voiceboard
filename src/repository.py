from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from src.db import connect


SCHEMA = """
CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    classification_mode TEXT NOT NULL CHECK (classification_mode IN ('rule', 'deepseek')),
    total_rows INTEGER NOT NULL CHECK (total_rows >= 0),
    inserted_rows INTEGER NOT NULL DEFAULT 0 CHECK (inserted_rows >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    fingerprint TEXT NOT NULL UNIQUE,
    feedback_id TEXT,
    feedback_text TEXT NOT NULL CHECK (length(trim(feedback_text)) > 0),
    country TEXT NOT NULL,
    user_type TEXT NOT NULL,
    product_category TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN ('物流', '支付', '商品质量', '搜索推荐', '客服', '退换货', '待确认')
    ),
    impact_level INTEGER NOT NULL CHECK (impact_level BETWEEN 1 AND 5),
    classification_source TEXT NOT NULL CHECK (
        classification_source IN ('rule', 'deepseek', 'manual')
    ),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    classification_reason TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feedback_dimensions
ON feedback(country, user_type, product_category, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback(category);

CREATE TABLE IF NOT EXISTS feedback_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL REFERENCES feedback(id),
    previous_category TEXT NOT NULL,
    new_category TEXT NOT NULL,
    previous_impact INTEGER NOT NULL,
    new_impact INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roadmap_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT UNIQUE,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    category TEXT NOT NULL CHECK (
        category IN ('物流', '支付', '商品质量', '搜索推荐', '客服', '退换货')
    ),
    frequency INTEGER NOT NULL CHECK (frequency >= 0),
    average_impact REAL NOT NULL CHECK (average_impact BETWEEN 1 AND 5),
    priority_score REAL NOT NULL CHECK (priority_score >= 0),
    filter_snapshot TEXT NOT NULL,
    solution TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '待评估' CHECK (
        status IN ('待评估', '已规划', '开发中', '已上线')
    ),
    target_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);
"""


FEEDBACK_COLUMNS = (
    "fingerprint",
    "feedback_id",
    "feedback_text",
    "country",
    "user_type",
    "product_category",
    "rating",
    "created_at",
    "category",
    "impact_level",
    "classification_source",
    "confidence",
    "classification_reason",
)

FILTER_COLUMNS = {"country", "user_type", "product_category", "category"}


class VoiceBoardRepository:
    def __init__(self, database: Path | str):
        self.database = Path(database)

    def initialize(self) -> None:
        with connect(self.database) as connection:
            connection.executescript(SCHEMA)

    def create_import_batch(self, filename: str, mode: str, total_rows: int) -> int:
        with connect(self.database) as connection:
            cursor = connection.execute(
                """
                INSERT INTO import_batches(filename, classification_mode, total_rows)
                VALUES (?, ?, ?)
                """,
                (filename, mode, total_rows),
            )
            return int(cursor.lastrowid)

    def insert_feedback_batch(
        self,
        batch_id: int,
        records: Iterable[Mapping[str, object]],
    ) -> int:
        placeholders = ", ".join("?" for _ in FEEDBACK_COLUMNS)
        columns = ", ".join(FEEDBACK_COLUMNS)
        statement = (
            f"INSERT INTO feedback(batch_id, {columns}) "
            f"VALUES (?, {placeholders}) "
            "ON CONFLICT(fingerprint) DO NOTHING"
        )
        inserted = 0
        with connect(self.database) as connection:
            for record in records:
                values = (batch_id, *(record[column] for column in FEEDBACK_COLUMNS))
                cursor = connection.execute(statement, values)
                inserted += cursor.rowcount
            connection.execute(
                "UPDATE import_batches SET inserted_rows = ? WHERE id = ?",
                (inserted, batch_id),
            )
        return inserted

    def count_feedback(self) -> int:
        with connect(self.database) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM feedback").fetchone()
            return int(row["count"])

    def list_fingerprints(self) -> set[str]:
        with connect(self.database) as connection:
            rows = connection.execute("SELECT fingerprint FROM feedback").fetchall()
            return {str(row["fingerprint"]) for row in rows}

    def import_feedback(
        self,
        filename: str,
        mode: str,
        total_rows: int,
        records: Iterable[Mapping[str, object]],
    ) -> tuple[int, int]:
        """Create the batch and all feedback in one transaction."""
        placeholders = ", ".join("?" for _ in FEEDBACK_COLUMNS)
        columns = ", ".join(FEEDBACK_COLUMNS)
        statement = (
            f"INSERT INTO feedback(batch_id, {columns}) "
            f"VALUES (?, {placeholders}) "
            "ON CONFLICT(fingerprint) DO NOTHING"
        )
        with connect(self.database) as connection:
            cursor = connection.execute(
                """
                INSERT INTO import_batches(filename, classification_mode, total_rows)
                VALUES (?, ?, ?)
                """,
                (filename, mode, total_rows),
            )
            batch_id = int(cursor.lastrowid)
            inserted = 0
            for record in records:
                values = (batch_id, *(record[column] for column in FEEDBACK_COLUMNS))
                inserted += connection.execute(statement, values).rowcount
            connection.execute(
                "UPDATE import_batches SET inserted_rows = ? WHERE id = ?",
                (inserted, batch_id),
            )
        return batch_id, inserted

    def query_feedback(
        self,
        filters: Mapping[str, object],
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses, parameters = _feedback_filters(filters)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect(self.database) as connection:
            count = connection.execute(
                f"SELECT COUNT(*) AS count FROM feedback{where}", parameters
            ).fetchone()["count"]
            rows = connection.execute(
                f"""
                SELECT * FROM feedback{where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (*parameters, max(1, min(limit, 20_000)), max(0, offset)),
            ).fetchall()
        return [dict(row) for row in rows], int(count)

    def distinct_feedback_values(self, column: str) -> list[str]:
        if column not in FILTER_COLUMNS:
            raise ValueError("不支持的筛选字段")
        with connect(self.database) as connection:
            rows = connection.execute(
                f"SELECT DISTINCT {column} FROM feedback ORDER BY {column}"
            ).fetchall()
        return [str(row[column]) for row in rows if row[column]]

    def revise_feedback(
        self,
        feedback_id: int,
        category: str,
        impact_level: int,
        reason: str,
    ) -> None:
        with connect(self.database) as connection:
            current = connection.execute(
                "SELECT category, impact_level FROM feedback WHERE id = ?",
                (feedback_id,),
            ).fetchone()
            if current is None:
                raise ValueError("反馈记录不存在")
            connection.execute(
                """
                UPDATE feedback
                SET category = ?, impact_level = ?, classification_source = 'manual',
                    confidence = 1.0, classification_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (category, impact_level, reason, feedback_id),
            )
            connection.execute(
                """
                INSERT INTO feedback_revisions(
                    feedback_id, previous_category, new_category,
                    previous_impact, new_impact, reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    current["category"],
                    category,
                    current["impact_level"],
                    impact_level,
                    reason,
                ),
            )

    def create_roadmap_item(self, item: Mapping[str, object]) -> tuple[int, bool]:
        with connect(self.database) as connection:
            cursor = connection.execute(
                """
                INSERT INTO roadmap_items(
                    source_key, title, category, frequency, average_impact,
                    priority_score, filter_snapshot, solution, evidence_summary,
                    owner, target_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key) DO NOTHING
                """,
                (
                    item["source_key"],
                    item["title"],
                    item["category"],
                    item["frequency"],
                    item["average_impact"],
                    item["priority_score"],
                    item["filter_snapshot"],
                    item["solution"],
                    item["evidence_summary"],
                    item.get("owner", ""),
                    item.get("target_version", ""),
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT id FROM roadmap_items WHERE source_key = ?",
                (item["source_key"],),
            ).fetchone()
        return int(row["id"]), created

    def list_roadmap_items(self, include_archived: bool = False) -> list[dict]:
        where = "" if include_archived else " WHERE archived_at IS NULL"
        with connect(self.database) as connection:
            rows = connection.execute(
                f"SELECT * FROM roadmap_items{where} ORDER BY priority_score DESC, id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_roadmap_item(
        self,
        item_id: int,
        *,
        title: str,
        solution: str,
        owner: str,
        status: str,
        target_version: str,
    ) -> None:
        with connect(self.database) as connection:
            cursor = connection.execute(
                """
                UPDATE roadmap_items
                SET title = ?, solution = ?, owner = ?, status = ?,
                    target_version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, solution, owner, status, target_version, item_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("需求卡不存在")

    def set_roadmap_archived(self, item_id: int, archived: bool) -> None:
        archived_at = "CURRENT_TIMESTAMP" if archived else "NULL"
        with connect(self.database) as connection:
            cursor = connection.execute(
                f"""
                UPDATE roadmap_items
                SET archived_at = {archived_at}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("需求卡不存在")


def _feedback_filters(filters: Mapping[str, object]) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    for column in FILTER_COLUMNS:
        value = filters.get(column)
        if value:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    if filters.get("date_from"):
        clauses.append("created_at >= ?")
        parameters.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("created_at <= ?")
        parameters.append(filters["date_to"])
    return clauses, parameters

