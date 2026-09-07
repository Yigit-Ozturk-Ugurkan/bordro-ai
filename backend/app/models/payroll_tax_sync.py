"""Immutable evidence for revision-aware authoritative tax-ledger sync."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin


class PayrollTaxLedgerSync(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_tax_ledger_syncs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["materialization_id", "organization_id", "payroll_id",
             "payroll_version_id"],
            ["payroll_import_materializations.id",
             "payroll_import_materializations.organization_id",
             "payroll_import_materializations.payroll_id",
             "payroll_import_materializations.payroll_version_id"],
            name="fk_tax_sync_materialization_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tax_calculation_run_id", "organization_id", "employee_id",
             "tax_year", "ruleset_id", "payroll_version_id"],
            ["tax_calculation_runs.id", "tax_calculation_runs.organization_id",
             "tax_calculation_runs.employee_id", "tax_calculation_runs.tax_year",
             "tax_calculation_runs.rule_set_id",
             "tax_calculation_runs.payroll_version_id"],
            name="fk_tax_sync_calculation_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tax_cumulative_record_id", "tax_calculation_run_id", "employee_id",
             "payroll_version_id", "tax_year", "period_month"],
            ["tax_cumulative_records.id",
             "tax_cumulative_records.calculation_run_id",
             "tax_cumulative_records.employee_id",
             "tax_cumulative_records.payroll_version_id",
             "tax_cumulative_records.tax_year",
             "tax_cumulative_records.period_month"],
            name="fk_tax_sync_cumulative_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint("materialization_id", name="uq_tax_sync_materialization"),
        UniqueConstraint("payroll_version_id", name="uq_tax_sync_payroll_version"),
        UniqueConstraint("tax_calculation_run_id", name="uq_tax_sync_calculation_run"),
        UniqueConstraint(
            "tax_cumulative_record_id", name="uq_tax_sync_cumulative_record",
        ),
        UniqueConstraint("supersedes_sync_id", name="uq_tax_sync_supersedes"),
        CheckConstraint("tax_year >= 2000", name="ck_tax_sync_year_valid"),
        CheckConstraint(
            "period_year = tax_year", name="ck_tax_sync_period_tax_year",
        ),
        CheckConstraint(
            "period_month >= 1 AND period_month <= 12",
            name="ck_tax_sync_period_month_valid",
        ),
        CheckConstraint(
            "length(payroll_source_checksum) = 64",
            name="ck_tax_sync_payroll_checksum",
        ),
        CheckConstraint(
            "length(result_checksum) = 64", name="ck_tax_sync_result_checksum",
        ),
        CheckConstraint(
            "reconciliation_status = 'MATCHED'",
            name="ck_tax_sync_reconciliation_matched",
        ),
        Index(
            "ix_tax_sync_org_import", "organization_id", "payroll_import_id",
        ),
        Index(
            "ix_tax_sync_employee_year_period",
            "organization_id", "employee_id", "tax_year", "period_month",
        ),
        Index(
            "uq_tax_sync_current_period",
            "organization_id", "employee_id", "tax_year", "period_month",
            unique=True, postgresql_where=text("is_current = true"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_imports.id", ondelete="RESTRICT"),
        nullable=False,
    )
    materialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    payroll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payrolls.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_calculation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    tax_cumulative_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    prior_sync_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_tax_ledger_syncs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    supersedes_sync_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_tax_ledger_syncs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_rule_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ruleset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payroll_source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    result_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="MATCHED",
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    synced_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


__all__ = ["PayrollTaxLedgerSync"]
