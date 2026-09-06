"""Public payroll-import API schemas; storage keys are intentionally absent."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus
from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollFieldMappingStatus,
    PayrollFieldParseStatus,
    PayrollImportReviewStatus,
    PayrollReviewCorrectionAction,
    PayrollReviewFieldStatus,
    PayrollReviewValueProvenance,
)


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


class PayrollImportTypedValue(ImportModel):
    type: PayrollCanonicalValueType
    value: str | int


class PayrollImportMappedFieldRead(ImportModel):
    id: UUID
    source_field_id: UUID
    source_external_field_id: str
    source_label: str
    raw_value: str | None
    canonical_key: str | None
    section_key: str | None
    mapping_id: UUID | None
    mapping_version: int | None
    typed_value: PayrollImportTypedValue | None
    candidate_canonical_keys: list[str]
    mapping_status: PayrollFieldMappingStatus
    parse_status: PayrollFieldParseStatus
    review_status: PayrollImportFieldReviewStatus
    review_reason_codes: list[str]


class PayrollImportMappedFieldList(ImportModel):
    import_id: UUID
    count: int
    items: list[PayrollImportMappedFieldRead]


class PayrollImportMappingIssueRead(ImportModel):
    canonical_key: str
    section_key: str
    target_value_type: PayrollCanonicalValueType
    issue_code: str
    review_status: PayrollImportFieldReviewStatus


class PayrollImportMappingSummary(ImportModel):
    import_id: UUID
    source_field_count: int
    mapped_count: int
    unmapped_count: int
    ambiguous_count: int
    parse_failed_count: int
    missing_count: int
    review_required_count: int
    issues: list[PayrollImportMappingIssueRead]


class PayrollReviewCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_review_version: int = Field(ge=1)
    canonical_key: str | None = Field(default=None, min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("value", "reason")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class PayrollReviewRevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_review_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class PayrollReviewFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_review_version: int = Field(ge=1)


class PayrollReviewTypedValue(ImportModel):
    type: PayrollCanonicalValueType
    value: str | int


class PayrollReviewSourceRead(ImportModel):
    field_id: UUID
    external_field_id: str
    label: str
    source_text: str | None
    raw_value: str | None
    normalized_value: str | None
    source_value_type: str | None
    confidence: str | None
    page_number: int | None
    bbox: list | None
    extraction_source: str | None
    staging_review_status: PayrollImportFieldReviewStatus


class PayrollReviewAdapterRead(ImportModel):
    mapped_field_id: UUID
    canonical_key: str | None
    section_key: str | None
    mapping_status: PayrollFieldMappingStatus
    parse_status: PayrollFieldParseStatus
    typed_value: PayrollReviewTypedValue | None
    candidate_canonical_keys: list[str]
    review_status: PayrollImportFieldReviewStatus
    review_reason_codes: list[str]
    fingerprint: str


class PayrollReviewCorrectionRead(ImportModel):
    id: UUID
    revision: int
    action: PayrollReviewCorrectionAction
    canonical_key: str | None
    typed_value: PayrollReviewTypedValue | None
    reviewer_user_id: UUID
    reason: str
    created_at: datetime
    is_stale: bool


class PayrollReviewEffectiveRead(ImportModel):
    canonical_key: str | None
    section_key: str | None
    typed_value: PayrollReviewTypedValue | None
    provenance: PayrollReviewValueProvenance | None


class PayrollReviewFieldRead(ImportModel):
    source: PayrollReviewSourceRead
    adapter: PayrollReviewAdapterRead
    correction: PayrollReviewCorrectionRead | None
    correction_history: list[PayrollReviewCorrectionRead]
    effective: PayrollReviewEffectiveRead
    review_status: PayrollReviewFieldStatus
    issue_codes: list[str]


class PayrollReviewIssueRead(ImportModel):
    code: str
    canonical_key: str | None = None
    source_field_id: UUID | None = None


class PayrollImportReviewRead(ImportModel):
    id: UUID
    import_id: UUID
    status: PayrollImportReviewStatus
    version: int
    started_by_user_id: UUID
    started_at: datetime
    last_reviewed_by_user_id: UUID
    last_reviewed_at: datetime
    current_snapshot_id: UUID | None
    complete: bool
    issues: list[PayrollReviewIssueRead]
    fields: list[PayrollReviewFieldRead]


class PayrollReviewSnapshotSummary(ImportModel):
    id: UUID
    import_id: UUID
    review_id: UUID
    snapshot_version: int
    created_by_user_id: UUID
    created_at: datetime
    source_staging_checksum: str
    adapter_output_checksum: str
    review_corrections_checksum: str
    snapshot_checksum: str
    field_count: int
    issue_count: int


class PayrollReviewSnapshotFieldRead(ImportModel):
    id: UUID
    source_import_field_id: UUID
    source_mapped_field_id: UUID | None
    source_field_id: str
    source_label: str
    source_text: str | None
    raw_value: str | None
    source_value_type: str | None
    effective_canonical_key: str | None
    section_key: str | None
    typed_value: PayrollReviewTypedValue
    provenance: PayrollReviewValueProvenance
    confidence: str | None
    page_number: int | None
    bbox: list | None
    extraction_source: str | None
    original_mapping_status: PayrollFieldMappingStatus
    review_status: PayrollReviewFieldStatus
    correction_id: UUID | None
    adapter_fingerprint: str


class PayrollReviewSnapshotRead(PayrollReviewSnapshotSummary):
    fields: list[PayrollReviewSnapshotFieldRead]


class PayrollReviewSnapshotList(ImportModel):
    import_id: UUID
    count: int
    items: list[PayrollReviewSnapshotSummary]


__all__ = [
    "PayrollImportFieldList", "PayrollImportFieldRead", "PayrollImportList",
    "PayrollImportListItem", "PayrollImportRead", "PayrollImportMappedFieldList",
    "PayrollImportMappedFieldRead", "PayrollImportMappingSummary",
    "PayrollImportReviewRead", "PayrollReviewCorrectionRequest",
    "PayrollReviewFinalizeRequest", "PayrollReviewRevertRequest",
    "PayrollReviewSnapshotList", "PayrollReviewSnapshotRead",
]
