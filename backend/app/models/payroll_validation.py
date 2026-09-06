"""Immutable, versioned validation runs over reviewed payroll-import snapshots."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import (
    PayrollValidationCategory,
    PayrollValidationRunStatus,
    PayrollValidationSeverity,
)
from app.models.payroll_review import CANONICAL_KEY_CHECK


class PayrollImportValidationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_validation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_snapshot_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.organization_id"],
            name="fk_validation_run_snapshot_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_validation_run_import_org", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "review_snapshot_id", "ruleset_version",
            name="uq_validation_run_snapshot_ruleset",
        ),
        UniqueConstraint(
            "id", "review_snapshot_id", "organization_id",
            name="uq_validation_run_identity_scope",
        ),
        CheckConstraint(
            "validation_version >= 1", name="ck_validation_run_version_positive",
        ),
        CheckConstraint(
            "ruleset_version >= 1", name="ck_validation_ruleset_version_positive",
        ),
        CheckConstraint(
            "info_count >= 0 AND warning_count >= 0 AND error_count >= 0 "
            "AND blocking_count >= 0",
            name="ck_validation_run_counts_non_negative",
        ),
        CheckConstraint(
            "length(snapshot_checksum) = 64",
            name="ck_validation_run_snapshot_checksum_length",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND result_checksum IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND result_checksum IS NOT NULL AND length(result_checksum) = 64) OR "
            "(status = 'FAILED' AND completed_at IS NOT NULL)",
            name="ck_validation_run_status_shape",
        ),
        Index(
            "ix_validation_run_org_import", "organization_id", "payroll_import_id",
        ),
        Index(
            "ix_validation_run_snapshot", "review_snapshot_id", "ruleset_version",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    validation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PayrollValidationRunStatus] = mapped_column(
        Enum(PayrollValidationRunStatus, name="payrollvalidationrunstatus"), nullable=False,
    )
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    result_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocking_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    results = relationship(
        "PayrollImportValidationResult", back_populates="run",
        cascade="save-update, merge", order_by="PayrollImportValidationResult.result_order",
    )


class PayrollImportValidationResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_validation_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["validation_run_id", "review_snapshot_id", "organization_id"],
            ["payroll_import_validation_runs.id",
             "payroll_import_validation_runs.review_snapshot_id",
             "payroll_import_validation_runs.organization_id"],
            name="fk_validation_result_run_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "validation_run_id", "result_order",
            name="uq_validation_result_run_order",
        ),
        CheckConstraint(
            "result_order >= 1", name="ck_validation_result_order_positive",
        ),
        CheckConstraint(
            "validation_version >= 1", name="ck_validation_result_version_positive",
        ),
        CheckConstraint(
            f"canonical_key IS NULL OR canonical_key IN {CANONICAL_KEY_CHECK}",
            name="ck_validation_result_canonical_key",
        ),
        CheckConstraint(
            "(severity IN ('ERROR','BLOCKING') AND blocks_future_approval) OR "
            "(severity IN ('INFO','WARNING') AND NOT blocks_future_approval)",
            name="ck_validation_result_blocking_semantics",
        ),
        Index(
            "ix_validation_result_org_run", "organization_id", "validation_run_id",
        ),
        Index(
            "ix_validation_result_snapshot_code", "review_snapshot_id", "validation_code",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    validation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    result_order: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_code: Mapped[str] = mapped_column(String(100), nullable=False)
    validation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[PayrollValidationCategory] = mapped_column(
        Enum(PayrollValidationCategory, name="payrollvalidationcategory"), nullable=False,
    )
    severity: Mapped[PayrollValidationSeverity] = mapped_column(
        Enum(PayrollValidationSeverity, name="payrollvalidationseverity"), nullable=False,
    )
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_snapshot_field_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    blocks_future_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    run = relationship("PayrollImportValidationRun", back_populates="results")


__all__ = ["PayrollImportValidationResult", "PayrollImportValidationRun"]
