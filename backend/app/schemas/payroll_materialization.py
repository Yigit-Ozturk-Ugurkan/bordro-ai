"""Public contracts for authoritative payroll materialization."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import PayrollVersionStatus


class MaterializationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PayrollMaterializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayrollMaterializationRead(MaterializationModel):
    id: UUID
    import_id: UUID
    approval_id: UUID
    snapshot_id: UUID
    validation_run_id: UUID
    payroll_id: UUID
    payroll_version_id: UUID
    revision_no: int
    version_status: PayrollVersionStatus
    employee_id: UUID
    period_year: int
    period_month: int
    materialization_version: int
    materialization_checksum: str
    materialized_by_user_id: UUID
    materialized_at: datetime


class PayrollMaterializationStateRead(MaterializationModel):
    import_id: UUID
    materialized: bool
    materialization: PayrollMaterializationRead | None


__all__ = [
    "PayrollMaterializationRead", "PayrollMaterializationStateRead",
    "PayrollMaterializeRequest",
]
