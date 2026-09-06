"""API contracts for deterministic payroll snapshot validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    PayrollValidationCategory,
    PayrollValidationReadiness,
    PayrollValidationRunStatus,
    PayrollValidationSeverity,
)


class ValidationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PayrollValidationResultRead(ValidationModel):
    id: UUID
    validation_code: str
    validation_version: int
    category: PayrollValidationCategory
    severity: PayrollValidationSeverity
    message: str
    canonical_key: str | None
    related_snapshot_field_ids: list[UUID]
    expected_value: str | None
    actual_value: str | None
    details: dict
    blocks_future_approval: bool
    created_at: datetime


class PayrollValidationRunRead(ValidationModel):
    id: UUID
    import_id: UUID
    snapshot_id: UUID
    validation_version: int
    ruleset_version: int
    status: PayrollValidationRunStatus
    readiness: PayrollValidationReadiness
    snapshot_checksum: str
    result_checksum: str
    started_at: datetime
    completed_at: datetime
    created_by_user_id: UUID
    info_count: int
    warning_count: int
    error_count: int
    blocking_count: int
    created_at: datetime
    results: list[PayrollValidationResultRead]


class PayrollValidationRunList(ValidationModel):
    import_id: UUID
    count: int
    items: list[PayrollValidationRunRead]


__all__ = [
    "PayrollValidationResultRead", "PayrollValidationRunList", "PayrollValidationRunRead",
]
