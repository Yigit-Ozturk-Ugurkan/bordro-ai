"""
Payroll detail models: earnings, deductions, and absences.

These models represent the line-item details of a PayrollVersion.
They are immutable sub-details of a specific PayrollVersion revision.

Design decisions:
- All code/reason_code fields are VARCHAR (not DB enums) to support
  company-specific custom codes without requiring schema migration.
- Financial amounts use NUMERIC(18,2) — never float.
- Rates use NUMERIC(9,6) for precision.
- Day counts use NUMERIC(5,2) to support half-day absences.
- ON DELETE CASCADE from payroll_versions: these are not independent
  financial documents but bound sub-records of a specific revision.
- PayrollAbsence.gross_effect convention:
    * Negative value (<= 0) means the absence REDUCED gross earnings.
    * Zero means no financial impact (e.g., paid leave).
    * This sign convention is chosen so that summing gross_effect
      across absences directly yields the total gross reduction.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin


def _provenance_constraints(kind: str) -> tuple:
    return (
        ForeignKeyConstraint(
            ["source_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name=f"fk_payroll_{kind}_source_import_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_table_id", "organization_id"],
            ["payroll_import_tables.id", "payroll_import_tables.organization_id"],
            name=f"fk_payroll_{kind}_source_table_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_row_id", "source_table_id", "organization_id"],
            ["payroll_import_table_rows.id", "payroll_import_table_rows.table_id", "payroll_import_table_rows.organization_id"],
            name=f"fk_payroll_{kind}_source_row_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["detail_snapshot_row_id", "organization_id"],
            ["payroll_import_detail_snapshot_rows.id", "payroll_import_detail_snapshot_rows.organization_id"],
            name=f"fk_payroll_{kind}_snapshot_row_org", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["detail_materialization_id", "organization_id", "payroll_version_id"],
            ["payroll_import_detail_materializations.id", "payroll_import_detail_materializations.organization_id", "payroll_import_detail_materializations.payroll_version_id"],
            name=f"fk_payroll_{kind}_detail_materialization_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint("detail_snapshot_row_id", name=f"uq_payroll_{kind}_snapshot_row"),
        CheckConstraint(
            "(detail_materialization_id IS NULL AND detail_snapshot_row_id IS NULL "
            "AND source_import_id IS NULL AND source_table_id IS NULL "
            "AND source_row_id IS NULL AND organization_id IS NULL) OR "
            "(detail_materialization_id IS NOT NULL AND detail_snapshot_row_id IS NOT NULL "
            "AND source_import_id IS NOT NULL AND source_table_id IS NOT NULL "
            "AND source_row_id IS NOT NULL AND organization_id IS NOT NULL)",
            name=f"ck_payroll_{kind}_provenance_complete",
        ),
    )


class PayrollDetailProvenanceMixin:
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_table_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_row_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detail_snapshot_row_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detail_materialization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class PayrollEarning(PayrollDetailProvenanceMixin, UUIDPrimaryKeyMixin, Base):
    """
    A single earning line within a PayrollVersion.

    Examples: BASE_SALARY, OVERTIME, BONUS, MEAL_ALLOWANCE, TRANSPORT_ALLOWANCE.
    Codes are free-form strings to allow company-specific earning types.

    Subject amount fields track how much of this earning is subject to
    specific tax/social-security calculations:
    - sgk_subject_amount: SGK (social security) base contribution
    - income_tax_subject_amount: gelir vergisi matrahına dahil tutar
    - stamp_tax_subject_amount: damga vergisi matrahına dahil tutar
    """

    __tablename__ = "payroll_earnings"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_payroll_earning_amount_non_negative",
        ),
        CheckConstraint(
            "sgk_subject_amount >= 0",
            name="ck_payroll_earning_sgk_subject_non_negative",
        ),
        CheckConstraint(
            "income_tax_subject_amount >= 0",
            name="ck_payroll_earning_income_tax_subject_non_negative",
        ),
        CheckConstraint(
            "stamp_tax_subject_amount >= 0",
            name="ck_payroll_earning_stamp_tax_subject_non_negative",
        ),
        Index(
            "ix_payroll_earnings_version_id",
            "payroll_version_id",
        ),
        Index(
            "ix_payroll_earnings_version_code",
            "payroll_version_id",
            "code",
        ),
    ) + _provenance_constraints("earning")

    payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric,
        nullable=True,
    )

    unit_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    sgk_subject_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    income_tax_subject_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    stamp_tax_subject_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    payroll_version = relationship(
        "PayrollVersion",
        back_populates="earnings",
    )


class PayrollDeduction(PayrollDetailProvenanceMixin, UUIDPrimaryKeyMixin, Base):
    """
    A single deduction line within a PayrollVersion.

    Examples: SGK_EMPLOYEE, UNEMPLOYMENT, INCOME_TAX, STAMP_TAX,
    ADVANCE, PRIVATE_INSURANCE, GARNISHMENT, UNION_DUE.

    Codes are free-form strings to allow company-specific deduction types.

    Fields:
    - base_amount: the base on which the deduction rate was applied (nullable).
    - rate: the rate applied to base_amount (nullable, must be 0..1 if set).
    - is_statutory: True for legally mandated deductions (SGK, tax, etc.).
    - is_sensitive: True for deductions requiring RBAC/AI filtering
      (e.g., garnishment, private insurance). Will be used by future
      AI layer to decide what data the LLM can see.
    """

    __tablename__ = "payroll_deductions"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_payroll_deduction_amount_non_negative",
        ),
        CheckConstraint(
            "base_amount IS NULL OR base_amount >= 0",
            name="ck_payroll_deduction_base_amount_non_negative",
        ),
        CheckConstraint(
            "rate IS NULL OR (rate >= 0 AND rate <= 1)",
            name="ck_payroll_deduction_rate_valid_range",
        ),
        Index(
            "ix_payroll_deductions_version_id",
            "payroll_version_id",
        ),
        Index(
            "ix_payroll_deductions_version_code",
            "payroll_version_id",
            "code",
        ),
    ) + _provenance_constraints("deduction")

    payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    base_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    rate: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6),
        nullable=True,
    )

    is_statutory: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    is_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    payroll_version = relationship(
        "PayrollVersion",
        back_populates="deductions",
    )


class PayrollAbsence(PayrollDetailProvenanceMixin, UUIDPrimaryKeyMixin, Base):
    """
    A single absence record within a PayrollVersion.

    Tracks missing/absent days and their financial impact on gross earnings.

    Sign convention for gross_effect:
        * gross_effect <= 0: the absence REDUCED gross earnings (most common).
          Example: 2 unpaid sick days → gross_effect = -1200.00
        * gross_effect = 0 or NULL: no financial impact (paid leave).
        * This convention ensures that SUM(gross_effect) across all absences
          directly yields the total gross reduction amount.
        * Positive gross_effect is intentionally not constrained at DB level
          to allow edge cases (e.g., retroactive corrections), but the
          application layer should treat negative as the standard direction.

    day_count must be strictly positive (> 0). Half-days are supported
    via NUMERIC(5,2), e.g., day_count = 0.50.
    """

    __tablename__ = "payroll_absences"
    __table_args__ = (
        CheckConstraint(
            "day_count > 0",
            name="ck_payroll_absence_day_count_positive",
        ),
        Index(
            "ix_payroll_absences_version_id",
            "payroll_version_id",
        ),
    ) + _provenance_constraints("absence")

    payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    reason_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    day_count: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )

    is_paid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    gross_effect: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    payroll_version = relationship(
        "PayrollVersion",
        back_populates="absences",
    )
