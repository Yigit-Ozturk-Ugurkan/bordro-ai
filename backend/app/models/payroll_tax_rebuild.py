"""Durable plans and item evidence for explicit cumulative-tax rebuilds."""

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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin


class PayrollTaxLedgerRebuild(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_tax_ledger_rebuilds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["trigger_payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_tax_rebuild_import_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["trigger_materialization_id", "organization_id",
             "trigger_payroll_id", "trigger_payroll_version_id"],
            ["payroll_import_materializations.id",
             "payroll_import_materializations.organization_id",
             "payroll_import_materializations.payroll_id",
             "payroll_import_materializations.payroll_version_id"],
            name="fk_tax_rebuild_materialization_scope", ondelete="RESTRICT",
        ),
        CheckConstraint("tax_year >= 2000", name="ck_tax_rebuild_year_valid"),
        CheckConstraint(
            "trigger_period_year = tax_year",
            name="ck_tax_rebuild_trigger_tax_year",
        ),
        CheckConstraint(
            "trigger_period_month BETWEEN 1 AND 12",
            name="ck_tax_rebuild_trigger_month",
        ),
        CheckConstraint(
            "status IN ('PLANNED', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_tax_rebuild_status",
        ),
        CheckConstraint("length(plan_checksum) = 64", name="ck_tax_rebuild_plan_checksum"),
        CheckConstraint(
            "prior_sync_result_checksum IS NULL OR "
            "length(prior_sync_result_checksum) = 64",
            name="ck_tax_rebuild_prior_checksum",
        ),
        CheckConstraint(
            "(prior_sync_id IS NULL) = (prior_cumulative_record_id IS NULL) "
            "AND (prior_sync_id IS NULL) = "
            "(prior_sync_result_checksum IS NULL)",
            name="ck_tax_rebuild_prior_evidence_complete",
        ),
        CheckConstraint(
            "result_checksum IS NULL OR length(result_checksum) = 64",
            name="ck_tax_rebuild_result_checksum",
        ),
        Index(
            "ix_tax_rebuild_org_import_created", "organization_id",
            "trigger_payroll_import_id", "created_at",
        ),
        Index(
            "uq_tax_rebuild_actionable_chain", "organization_id", "employee_id",
            "tax_year", unique=True,
            postgresql_where=text("status IN ('PLANNED', 'RUNNING')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_payroll_import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    trigger_materialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    trigger_payroll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payrolls.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trigger_payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trigger_period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_sync_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_tax_ledger_syncs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    prior_cumulative_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_cumulative_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    prior_sync_result_checksum: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PLANNED")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    executed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    result_checksum: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)

    items = relationship(
        "PayrollTaxLedgerRebuildItem", back_populates="rebuild",
        order_by="PayrollTaxLedgerRebuildItem.sequence",
    )


class PayrollTaxLedgerRebuildItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_tax_ledger_rebuild_items"
    __table_args__ = (
        UniqueConstraint("rebuild_id", "sequence", name="uq_tax_rebuild_item_sequence"),
        UniqueConstraint(
            "rebuild_id", "payroll_version_id",
            name="uq_tax_rebuild_item_version",
        ),
        CheckConstraint("sequence >= 1", name="ck_tax_rebuild_item_sequence"),
        CheckConstraint(
            "period_month BETWEEN 1 AND 12", name="ck_tax_rebuild_item_month",
        ),
        CheckConstraint(
            "execution_status IN ('PENDING', 'COMPLETED')",
            name="ck_tax_rebuild_item_status",
        ),
        CheckConstraint(
            "length(payroll_version_checksum) = 64",
            name="ck_tax_rebuild_item_version_checksum",
        ),
        CheckConstraint(
            "length(ruleset_checksum) = 64",
            name="ck_tax_rebuild_item_ruleset_checksum",
        ),
        CheckConstraint(
            "old_sync_result_checksum IS NULL OR "
            "length(old_sync_result_checksum) = 64",
            name="ck_tax_rebuild_item_old_checksum",
        ),
        Index("ix_tax_rebuild_item_order", "rebuild_id", "sequence"),
    )

    rebuild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_tax_ledger_rebuilds.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_imports.id", ondelete="RESTRICT"),
        nullable=False,
    )
    materialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_import_materializations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payroll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payrolls.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    old_tax_sync_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_tax_ledger_syncs.id", ondelete="RESTRICT"),
    )
    old_cumulative_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_cumulative_records.id", ondelete="RESTRICT"),
    )
    old_sync_result_checksum: Mapped[str | None] = mapped_column(String(64))
    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_rule_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ruleset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ruleset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payroll_version_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING",
    )
    new_tax_calculation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_calculation_runs.id", ondelete="RESTRICT"),
    )
    new_tax_sync_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_tax_ledger_syncs.id", ondelete="RESTRICT"),
    )
    new_cumulative_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_cumulative_records.id", ondelete="RESTRICT"),
    )
    reconciliation_status: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    rebuild = relationship("PayrollTaxLedgerRebuild", back_populates="items")


__all__ = ["PayrollTaxLedgerRebuild", "PayrollTaxLedgerRebuildItem"]
