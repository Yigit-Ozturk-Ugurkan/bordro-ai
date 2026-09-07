"""API contracts for human payroll-import approval evidence."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    PayrollApprovalDecision,
    PayrollApprovalStatus,
    PayrollValidationReadiness,
)


class ApprovalModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PayrollWarningAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class PayrollApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class PayrollRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class PayrollWarningAcknowledgementRead(ApprovalModel):
    id: UUID
    validation_run_id: UUID
    validation_result_id: UUID
    acknowledged_by_user_id: UUID
    note: str | None
    acknowledged_at: datetime


class PayrollApprovalDecisionRead(ApprovalModel):
    id: UUID
    snapshot_id: UUID
    validation_run_id: UUID
    snapshot_checksum: str
    validation_result_checksum: str
    validation_ruleset_version: int
    decision: PayrollApprovalDecision
    decision_reason: str | None
    acknowledged_warning_result_ids: list[UUID]
    approval_checksum: str
    decided_by_user_id: UUID
    decided_at: datetime


class PayrollApprovalWarningSummary(ApprovalModel):
    total: int
    acknowledged: int
    remaining: int


class PayrollApprovalStateRead(ApprovalModel):
    import_id: UUID
    snapshot_id: UUID | None
    validation_run_id: UUID | None
    validation_readiness: PayrollValidationReadiness | None
    approval_status: PayrollApprovalStatus
    decision: PayrollApprovalDecisionRead | None
    warnings: PayrollApprovalWarningSummary


class PayrollApprovalHistoryRead(ApprovalModel):
    import_id: UUID
    approval_count: int
    acknowledgement_count: int
    approvals: list[PayrollApprovalDecisionRead]
    acknowledgements: list[PayrollWarningAcknowledgementRead]


__all__ = [
    "PayrollApprovalDecisionRead", "PayrollApprovalHistoryRead",
    "PayrollApprovalStateRead", "PayrollApproveRequest", "PayrollRejectRequest",
    "PayrollWarningAcknowledgementRead", "PayrollWarningAcknowledgementRequest",
]
