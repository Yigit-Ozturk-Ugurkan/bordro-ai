"""Immutable evidence linking an approval to an authoritative payroll revision."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin


class PayrollImportMaterialization(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_materializations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_materialization_import_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "approval_id", "payroll_import_id", "review_snapshot_id",
                "validation_run_id", "organization_id",
            ],
            [
                "payroll_import_approvals.id",
                "payroll_import_approvals.payroll_import_id",
                "payroll_import_approvals.review_snapshot_id",
                "payroll_import_approvals.validation_run_id",
                "payroll_import_approvals.organization_id",
            ],
            name="fk_materialization_approval_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payroll_id", "organization_id"],
            ["payrolls.id", "payrolls.organization_id"],
            name="fk_materialization_payroll_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payroll_version_id", "payroll_id", "payroll_revision_no"],
            ["payroll_versions.id", "payroll_versions.payroll_id",
             "payroll_versions.revision_no"],
            name="fk_materialization_version_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint("approval_id", name="uq_materialization_approval"),
        UniqueConstraint("payroll_version_id", name="uq_materialization_payroll_version"),
        CheckConstraint(
            "materialization_version >= 1",
            name="ck_materialization_version_positive",
        ),
        CheckConstraint(
            "payroll_revision_no >= 1",
            name="ck_materialization_revision_positive",
        ),
        CheckConstraint(
            "length(snapshot_checksum) = 64",
            name="ck_materialization_snapshot_checksum",
        ),
        CheckConstraint(
            "length(validation_result_checksum) = 64",
            name="ck_materialization_validation_checksum",
        ),
        CheckConstraint(
            "length(approval_checksum) = 64",
            name="ck_materialization_approval_checksum",
        ),
        CheckConstraint(
            "length(materialization_checksum) = 64",
            name="ck_materialization_checksum",
        ),
        Index(
            "ix_materialization_org_import",
            "organization_id", "payroll_import_id", "materialized_at",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    validation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_result_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    materialization_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    materialization_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    materialized_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    materialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


__all__ = ["PayrollImportMaterialization"]
