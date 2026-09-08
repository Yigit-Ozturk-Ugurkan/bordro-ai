"""Public contracts for explicit cumulative-tax rebuild plans."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PayrollTaxRebuildCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayrollTaxRebuildExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayrollTaxRebuildItemRead(BaseModel):
    sequence: int
    payroll_id: UUID
    payroll_version_id: UUID
    period: str
    old_tax_sync_id: UUID | None
    old_cumulative_record_id: UUID | None
    execution_status: str
    new_tax_sync_id: UUID | None
    new_cumulative_record_id: UUID | None
    reconciliation_status: str | None


class PayrollTaxRebuildRead(BaseModel):
    id: UUID
    status: str
    employee_id: UUID
    tax_year: int
    trigger_period: str
    trigger_payroll_version_id: UUID
    affected_periods: list[str]
    affected_count: int
    plan_checksum: str
    result_checksum: str | None
    created_by_user_id: UUID
    executed_by_user_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    items: list[PayrollTaxRebuildItemRead]


class PayrollTaxRebuildList(BaseModel):
    items: list[PayrollTaxRebuildRead]


__all__ = [
    "PayrollTaxRebuildCreateRequest",
    "PayrollTaxRebuildExecuteRequest",
    "PayrollTaxRebuildItemRead",
    "PayrollTaxRebuildList",
    "PayrollTaxRebuildRead",
]
