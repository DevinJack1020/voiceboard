from __future__ import annotations

from dataclasses import dataclass, field

from src.classifiers.base import FeedbackClassifier
from src.classifiers.rule import RuleClassifier
from src.importer import CsvValidationError, RowError, parse_feedback_csv
from src.repository import VoiceBoardRepository


MAX_DEEPSEEK_RECORDS = 100


@dataclass
class PreparedImport:
    mode: str
    records: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    duplicate_count: int = 0

    @property
    def can_import(self) -> bool:
        return bool(self.records) and not self.errors


@dataclass(frozen=True)
class ImportOutcome:
    batch_id: int
    inserted_count: int
    duplicate_count: int


class ImportService:
    def __init__(self, repository: VoiceBoardRepository):
        self.repository = repository

    def prepare(
        self,
        content: bytes,
        mode: str,
        classifier: FeedbackClassifier | None = None,
    ) -> PreparedImport:
        if mode not in {"rule", "deepseek"}:
            raise ValueError("不支持的分类模式")
        preview = parse_feedback_csv(
            content,
            existing_fingerprints=self.repository.list_fingerprints(),
        )
        prepared = PreparedImport(
            mode=mode,
            errors=preview.errors,
            duplicate_count=preview.duplicate_count,
        )
        if preview.errors:
            return prepared
        if mode == "deepseek" and len(preview.records) > MAX_DEEPSEEK_RECORDS:
            raise CsvValidationError(
                f"DeepSeek 单批最多处理 {MAX_DEEPSEEK_RECORDS} 条反馈，"
                "请拆分文件或改用离线规则，避免意外 API 费用。"
            )
        selected = classifier or (RuleClassifier() if mode == "rule" else None)
        if selected is None:
            raise ValueError("DeepSeek 模式需要配置分类器")

        for record in preview.records:
            result = selected.classify(record)
            prepared.records.append(
                {
                    **record,
                    "category": result.category,
                    "impact_level": result.impact_level,
                    "classification_source": result.source,
                    "confidence": result.confidence,
                    "classification_reason": result.reason,
                }
            )
        return prepared

    def commit(self, filename: str, prepared: PreparedImport) -> ImportOutcome:
        if not prepared.can_import:
            raise ValueError("当前预览没有可导入记录")
        batch_id, inserted = self.repository.import_feedback(
            filename=filename,
            mode=prepared.mode,
            total_rows=len(prepared.records) + prepared.duplicate_count,
            records=prepared.records,
        )
        return ImportOutcome(
            batch_id=batch_id,
            inserted_count=inserted,
            duplicate_count=prepared.duplicate_count + len(prepared.records) - inserted,
        )
