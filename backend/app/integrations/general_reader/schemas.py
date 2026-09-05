"""Bordro-owned validation mirror of General Reader ExtractionResultV1."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProducerV1(ContractModel):
    name: str
    version: str


class TenantContextV1(ContractModel):
    namespace: str
    tenant_id: str


class DocumentV1(ContractModel):
    external_document_id: str | None
    internal_document_ids: list[int]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_filename: str
    page_count: int = Field(ge=1)


class TemplateMetadataV1(ContractModel):
    template_id: int | None
    template_version: int | None
    scope: str | None
    match_decision: str
    match_score: Decimal | None = Field(default=None, ge=0, le=1)
    match_component_scores: dict[str, Any]
    page_numbers: list[int]


class PageV1(ContractModel):
    page_number: int = Field(ge=1)
    internal_document_id: int
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    ocr_engine: str
    ocr_confidence: Decimal = Field(ge=0, le=1)
    box_count: int = Field(ge=0)
    line_count: int = Field(ge=0)
    template_id: int | None


class FieldV1(ContractModel):
    field_id: str
    source_label: str
    source_text: str | None
    raw_value: str | None
    normalized_value: str | None
    value_type: str
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    bbox: list[Decimal] | None = Field(default=None, min_length=4, max_length=4)
    coordinate_space: str
    page_number: int = Field(ge=1)
    extraction_source: str
    rule_index: int | None
    status: Literal["EXTRACTED", "LOW_CONFIDENCE", "MISSING"]
    warnings: list[str]


class MissingFieldV1(ContractModel):
    field_id: str
    source_label: str
    value_type: str
    required: bool
    reason_code: str
    safe_reason_text: str
    observed_value: str | None
    observed_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    page_number: int = Field(ge=1)


class TableColumnV1(ContractModel):
    column_id: str
    source_label: str
    value_type: str


class TableCellV1(ContractModel):
    column_id: str
    source_label: str
    raw_value: str | None
    normalized_value: str | None
    value_type: str
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    bbox: list[Decimal] | None = Field(default=None, min_length=4, max_length=4)
    coordinate_space: str
    extraction_source: str


class TableRowV1(ContractModel):
    row_index: int = Field(ge=0)
    page_number: int = Field(ge=1)
    bbox: list[Decimal] | None = Field(default=None, min_length=4, max_length=4)
    coordinate_space: str
    extraction_source: str
    cells: list[TableCellV1]


class TableV1(ContractModel):
    table_id: str
    source_label: str
    columns: list[TableColumnV1]
    rows: list[TableRowV1]
    page_numbers: list[int]
    warnings: list[str]


class ContractWarningV1(ContractModel):
    code: str
    message: str
    page_number: int | None = None
    field_id: str | None = None
    table_id: str | None = None


class PageTimingV1(ContractModel):
    page_number: int = Field(ge=1)
    ocr_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)


class TimingsV1(ContractModel):
    ocr_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)
    pages: list[PageTimingV1]


class ExtractionResultV1(ContractModel):
    schema_version: Literal["1.0"]
    producer: ProducerV1
    request_id: str
    correlation_id: str
    tenant_context: TenantContextV1
    document: DocumentV1
    templates: list[TemplateMetadataV1]
    pages: list[PageV1]
    fields: list[FieldV1]
    missing_fields: list[MissingFieldV1]
    tables: list[TableV1]
    warnings: list[ContractWarningV1]
    timings: TimingsV1


__all__ = ["ExtractionResultV1"]
