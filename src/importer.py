from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

import pandas as pd


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
REQUIRED_COLUMNS = (
    "feedback_text",
    "country",
    "user_type",
    "product_category",
    "rating",
    "created_at",
)
OPTIONAL_COLUMNS = ("feedback_id", "impact_level")
TEMPLATE_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


class CsvValidationError(ValueError):
    """Raised when a CSV cannot be safely parsed at all."""


@dataclass(frozen=True)
class RowError:
    row_number: int | None
    message: str


@dataclass
class ImportPreview:
    records: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    duplicate_count: int = 0

    @property
    def can_import(self) -> bool:
        return bool(self.records) and not self.errors


def build_template_csv() -> bytes:
    header = ",".join(TEMPLATE_COLUMNS) + "\n"
    return header.encode("utf-8-sig")


def parse_feedback_csv(
    content: bytes,
    existing_fingerprints: set[str] | None = None,
) -> ImportPreview:
    if len(content) > MAX_FILE_BYTES:
        raise CsvValidationError("CSV 文件不能超过 10 MB")
    try:
        frame = pd.read_csv(
            io.BytesIO(content),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
    except (UnicodeDecodeError, pd.errors.ParserError) as error:
        raise CsvValidationError("CSV 必须是 UTF-8 编码且格式完整") from error

    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        return ImportPreview(
            errors=[RowError(None, f"缺少必填列：{', '.join(missing)}")]
        )
    if len(frame) > MAX_ROWS:
        raise CsvValidationError(f"单次最多导入 {MAX_ROWS:,} 行反馈")

    preview = ImportPreview()
    seen = set(existing_fingerprints or set())
    for index, row in frame.iterrows():
        row_number = int(index) + 2
        normalized, errors = _normalize_row(row, row_number)
        if errors:
            preview.errors.extend(errors)
            continue
        fingerprint = _fingerprint(normalized)
        if fingerprint in seen:
            preview.duplicate_count += 1
            continue
        seen.add(fingerprint)
        normalized["fingerprint"] = fingerprint
        preview.records.append(normalized)
    return preview


def _normalize_row(row: pd.Series, row_number: int) -> tuple[dict, list[RowError]]:
    values = {column: str(row.get(column, "")).strip() for column in TEMPLATE_COLUMNS}
    errors: list[RowError] = []
    for column in REQUIRED_COLUMNS:
        if not values[column]:
            errors.append(RowError(row_number, f"{column} 不能为空"))

    rating = _bounded_integer(values["rating"], 1, 5)
    if rating is None:
        errors.append(RowError(row_number, "rating 必须是 1–5 的整数"))

    try:
        created_at = pd.to_datetime(values["created_at"], errors="raise").date().isoformat()
    except (ValueError, TypeError, OverflowError):
        created_at = ""
        errors.append(RowError(row_number, "created_at 不是有效日期"))

    raw_impact = values["impact_level"]
    impact = None if not raw_impact else _bounded_integer(raw_impact, 1, 5)
    if raw_impact and impact is None:
        errors.append(RowError(row_number, "impact_level 必须是 1–5 的整数或留空"))

    normalized = {
        "feedback_text": values["feedback_text"],
        "country": values["country"],
        "user_type": values["user_type"],
        "product_category": values["product_category"],
        "rating": rating,
        "created_at": created_at,
        "feedback_id": values["feedback_id"] or None,
        "impact_level": impact,
    }
    return normalized, errors


def _bounded_integer(value: str, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum and str(parsed) == value else None


def _fingerprint(record: dict) -> str:
    parts = (
        record["feedback_text"],
        record["country"],
        record["user_type"],
        record["product_category"],
        record["created_at"],
    )
    canonical = "\x1f".join(" ".join(str(part).casefold().split()) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
