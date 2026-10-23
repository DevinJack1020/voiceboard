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

