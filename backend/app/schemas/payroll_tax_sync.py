"""Public contracts for authoritative payroll tax-ledger sync."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PayrollTaxSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayrollTaxSyncRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_id: UUID
    materialization_id: UUID
    payroll_id: UUID
    payroll_version_id: UUID
    employee_id: UUID
    tax_year: int
    period_year: int
    period_month: int
    ruleset_id: UUID
    ruleset_version: str
    tax_calculation_run_id: UUID
    tax_cumulative_record_id: UUID
    prior_sync_id: UUID | None
    supersedes_sync_id: UUID | None
    opening_cumulative_base: str
    period_income_tax_base: str
    closing_cumulative_base: str
    calculated_withholding: str
    authoritative_payroll_withholding: str
    reconciliation_status: str
    result_checksum: str
    is_current: bool
    synced_by_user_id: UUID
    synced_at: datetime


class PayrollTaxSyncStateRead(BaseModel):
    import_id: UUID
    synced: bool
    tax_sync: PayrollTaxSyncRead | None


__all__ = [
    "PayrollTaxSyncRead", "PayrollTaxSyncRequest", "PayrollTaxSyncStateRead",
]
