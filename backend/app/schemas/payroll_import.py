"""Public payroll-import API schemas; storage keys are intentionally absent."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus


class ImportModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PayrollImportDocumentRead(ImportModel):
    id: UUID
    file_id: UUID
    original_filename: str
    declared_mime_type: str
    detected_mime_type: str
    size_bytes: int
    sha256: str
    storage_provider: str
    reader_document_id: str | None
    page_count: int | None
    created_at: datetime


class PayrollImportRead(ImportModel):
    id: UUID
    status: PayrollImportStatus
    source_type: str
    reader_provider: str
    content_sha256: str
    detected_employee_id: UUID | None
    detected_year: int | None
    detected_month: int | None
    template_external_id: str | None
    template_version: int | None
    template_scope: str | None
    template_match_score: Decimal | None
    extraction_schema_version: str | None
    reader_table_count: int
    reader_warning_codes: list[str]
    processing_attempt: int
    processing_started_at: datetime | None
    processed_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    document: PayrollImportDocumentRead


class PayrollImportListItem(ImportModel):
    id: UUID
    status: PayrollImportStatus
    original_filename: str
    size_bytes: int
    content_sha256: str
    processing_attempt: int
    created_at: datetime
    processed_at: datetime | None


class PayrollImportList(ImportModel):
    count: int
    items: list[PayrollImportListItem]


class PayrollImportFieldRead(ImportModel):
    id: UUID
    source_field_id: str
    source_label: str
    source_text: str | None
    raw_value: str | None
    normalized_value: str | None
    value_type: str | None
    confidence: Decimal | None
    page_number: int | None
    bbox: list | None
    coordinate_space: str | None
    extraction_source: str | None
    rule_index: int | None
    missing_reason_code: str | None
    missing_reason: str | None
    review_status: PayrollImportFieldReviewStatus
    created_at: datetime
    updated_at: datetime


class PayrollImportFieldList(ImportModel):
    import_id: UUID
    count: int
    items: list[PayrollImportFieldRead]


__all__ = [
    "PayrollImportFieldList", "PayrollImportFieldRead", "PayrollImportList",
    "PayrollImportListItem", "PayrollImportRead",
]
