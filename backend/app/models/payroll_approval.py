"""Immutable human decisions and warning acknowledgements for validation runs."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import PayrollApprovalDecision


class PayrollImportApproval(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_approval_import_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_snapshot_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.organization_id"],
            name="fk_import_approval_snapshot_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["validation_run_id", "review_snapshot_id", "organization_id"],
            ["payroll_import_validation_runs.id",
             "payroll_import_validation_runs.review_snapshot_id",
             "payroll_import_validation_runs.organization_id"],
            name="fk_import_approval_validation_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint("validation_run_id", name="uq_import_approval_validation_run"),
        UniqueConstraint(
            "id", "payroll_import_id", "review_snapshot_id", "validation_run_id",
            "organization_id", name="uq_import_approval_materialization_scope",
        ),
        CheckConstraint("length(snapshot_checksum) = 64", name="ck_import_approval_snapshot_checksum"),
        CheckConstraint(
            "length(validation_result_checksum) = 64",
            name="ck_import_approval_validation_checksum",
        ),
        CheckConstraint(
            "validation_ruleset_version >= 1",
            name="ck_import_approval_ruleset_version",
        ),
        CheckConstraint(
            "length(approval_checksum) = 64",
            name="ck_import_approval_checksum",
        ),
        CheckConstraint(
            "jsonb_typeof(acknowledged_warning_result_ids) = 'array'",
            name="ck_import_approval_warning_ids_array",
        ),
        CheckConstraint(
            "decision <> 'REJECTED' OR "
            "(decision_reason IS NOT NULL AND length(btrim(decision_reason)) > 0)",
            name="ck_import_approval_rejection_reason",
        ),
        Index("ix_import_approval_org_import", "organization_id", "payroll_import_id"),
        Index("ix_import_approval_snapshot", "review_snapshot_id", "validation_run_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    validation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_result_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_ruleset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[PayrollApprovalDecision] = mapped_column(
        Enum(PayrollApprovalDecision, name="payrollapprovaldecision"), nullable=False,
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_warning_result_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )
    approval_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class PayrollImportValidationAcknowledgement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_validation_acknowledgements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_validation_ack_import_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["validation_run_id", "review_snapshot_id", "organization_id"],
            ["payroll_import_validation_runs.id",
             "payroll_import_validation_runs.review_snapshot_id",
             "payroll_import_validation_runs.organization_id"],
            name="fk_validation_ack_run_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "validation_result_id", name="uq_validation_ack_warning_result",
        ),
        Index("ix_validation_ack_org_import", "organization_id", "payroll_import_id"),
        Index("ix_validation_ack_run", "validation_run_id", "validation_result_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    validation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    validation_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(
            "payroll_import_validation_results.id", ondelete="RESTRICT",
        ), nullable=False,
    )
    acknowledged_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


__all__ = ["PayrollImportApproval", "PayrollImportValidationAcknowledgement"]
