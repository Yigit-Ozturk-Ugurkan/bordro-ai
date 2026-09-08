"""API contracts for deterministic payroll-detail review and materialization."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PayrollDetailMappingStatus, PayrollDetailReviewStatus, PayrollDetailType


class DetailModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PayrollMappedDetailRead(DetailModel):
    id: UUID
    source_table_id: UUID
    source_row_id: UUID
    source_table_index: int
    source_row_index: int
    mapping_id: UUID | None
    source_label: str | None
    source_values: list
    source_checksum: str
    detail_type: PayrollDetailType
    canonical_code: str | None
    canonical_name: str | None
    category: str | None
    amount: Decimal | None
    quantity: Decimal | None
    rate: Decimal | None
    target_values: dict[str, Any]
    mapping_status: PayrollDetailMappingStatus
    review_required: bool


class PayrollMappedDetailList(DetailModel):
    import_id: UUID
    count: int
    mapping_checksum: str | None
    items: list[PayrollMappedDetailRead]


class PayrollDetailCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    expected_source_checksum: str = Field(min_length=64, max_length=64)
    detail_type: PayrollDetailType
    canonical_code: str | None = Field(default=None, max_length=100)
    canonical_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    amount: str | None = Field(default=None, max_length=100)
    quantity: str | None = Field(default=None, max_length=100)
    rate: str | None = Field(default=None, max_length=100)
    target_values: dict[str, Any] = Field(default_factory=dict)
    ignored: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("canonical_code", "canonical_name", "category", "reason")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class PayrollDetailCorrectionRead(DetailModel):
    id: UUID
    mapped_detail_id: UUID
    source_checksum: str
    revision: int
    detail_type: PayrollDetailType
    canonical_code: str | None
    canonical_name: str | None
    category: str | None
    amount: Decimal | None
    quantity: Decimal | None
    rate: Decimal | None
    target_values: dict[str, Any]
    ignored: bool
    reason: str
    reviewed_by_user_id: UUID
    created_at: datetime


class PayrollDetailReviewRead(DetailModel):
    import_id: UUID
    status: PayrollDetailReviewStatus
    row_version: int
    mapping_checksum: str
    current_snapshot_id: UUID | None
    mapped_count: int
    corrected_count: int
    unresolved_count: int
    corrections: list[PayrollDetailCorrectionRead]


class PayrollDetailFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)


class PayrollDetailSnapshotRowRead(DetailModel):
    id: UUID
    source_table_id: UUID
    source_row_id: UUID
    correction_id: UUID
    row_order: int
    source_checksum: str
    detail_type: PayrollDetailType
    canonical_code: str | None
    canonical_name: str | None
    category: str | None
    amount: Decimal | None
    quantity: Decimal | None
    rate: Decimal | None
    target_values: dict[str, Any]
    ignored: bool
    reviewed_by_user_id: UUID
    reviewed_at: datetime


class PayrollDetailSnapshotRead(DetailModel):
    id: UUID
    import_id: UUID = Field(validation_alias="payroll_import_id")
    revision: int
    mapping_checksum: str
    corrections_checksum: str
    snapshot_checksum: str
    row_count: int
    finalized_by_user_id: UUID
    finalized_at: datetime
    rows: list[PayrollDetailSnapshotRowRead]


class PayrollMaterializedDetailBase(DetailModel):
    id: UUID
    payroll_version_id: UUID
    organization_id: UUID
    source_import_id: UUID
    source_table_id: UUID
    source_row_id: UUID
    detail_snapshot_row_id: UUID
    detail_materialization_id: UUID
    created_at: datetime


class PayrollMaterializedEarningRead(PayrollMaterializedDetailBase):
    code: str
    label: str
    category: str
    quantity: Decimal | None
    unit_amount: Decimal | None
    amount: Decimal
    sgk_subject_amount: Decimal
    income_tax_subject_amount: Decimal
    stamp_tax_subject_amount: Decimal


class PayrollMaterializedDeductionRead(PayrollMaterializedDetailBase):
    code: str
    label: str
    category: str
    amount: Decimal
    base_amount: Decimal | None
    rate: Decimal | None
    is_statutory: bool
    is_sensitive: bool


class PayrollMaterializedAbsenceRead(PayrollMaterializedDetailBase):
    reason_code: str
    description: str | None
    day_count: Decimal
    is_paid: bool
    gross_effect: Decimal | None


class PayrollDetailMaterializationRead(DetailModel):
    id: UUID
    import_id: UUID = Field(validation_alias="payroll_import_id")
    detail_snapshot_id: UUID
    approval_id: UUID
    payroll_materialization_id: UUID
    payroll_id: UUID
    payroll_version_id: UUID
    materialization_checksum: str
    earning_count: int
    deduction_count: int
    absence_count: int
    materialized_by_user_id: UUID
    materialized_at: datetime
    earnings: list[PayrollMaterializedEarningRead]
    deductions: list[PayrollMaterializedDeductionRead]
    absences: list[PayrollMaterializedAbsenceRead]


__all__ = [name for name in globals() if name.startswith("Payroll")]
