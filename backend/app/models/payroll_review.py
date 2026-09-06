"""Reviewer-owned corrections and immutable reviewed payroll-import snapshots."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollFieldMappingStatus,
    PayrollImportReviewStatus,
    PayrollReviewCorrectionAction,
    PayrollReviewFieldStatus,
    PayrollReviewValueProvenance,
)


CANONICAL_KEY_CHECK = (
    "('employee_identifier','period_year','period_month','gross_earnings','sgk_base',"
    "'income_tax_base','stamp_tax_base','employee_sgk','employee_unemployment',"
    "'income_tax','stamp_tax','total_earnings','total_deductions','net_pay','paid_days',"
    "'missing_days','cumulative_income_tax_base')"
)


class PayrollImportReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_import_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_review_import_org", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["current_snapshot_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.organization_id"],
            name="fk_import_review_current_snapshot_org", ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint(
            "payroll_import_id", name="uq_import_review_payroll_import",
        ),
        UniqueConstraint(
            "id", "payroll_import_id", "organization_id",
            name="uq_import_review_identity_scope",
        ),
        CheckConstraint("row_version >= 1", name="ck_import_review_row_version_positive"),
        CheckConstraint(
            "length(adapter_output_checksum) = 64",
            name="ck_import_review_adapter_checksum_length",
        ),
        Index("ix_import_review_org_import", "organization_id", "payroll_import_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[PayrollImportReviewStatus] = mapped_column(
        Enum(PayrollImportReviewStatus, name="payrollimportreviewstatus"), nullable=False,
    )
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_reviewed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    last_reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    adapter_output_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PayrollImportFieldCorrection(UUIDPrimaryKeyMixin, Base):
    """Immutable correction revision; the latest action determines effective state."""

    __tablename__ = "payroll_import_field_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "payroll_import_id", "organization_id"],
            ["payroll_import_reviews.id", "payroll_import_reviews.payroll_import_id",
             "payroll_import_reviews.organization_id"],
            name="fk_field_correction_review_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payroll_import_field_id", "payroll_import_id", "organization_id"],
            ["payroll_import_fields.id", "payroll_import_fields.payroll_import_id",
             "payroll_import_fields.organization_id"],
            name="fk_field_correction_source_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "review_id", "payroll_import_field_id", "revision",
            name="uq_field_correction_review_source_revision",
        ),
        CheckConstraint("revision >= 1", name="ck_field_correction_revision_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_field_correction_reason_present"),
        CheckConstraint(
            f"original_canonical_key IS NULL OR original_canonical_key IN {CANONICAL_KEY_CHECK}",
            name="ck_field_correction_original_key",
        ),
        CheckConstraint(
            f"override_canonical_key IS NULL OR override_canonical_key IN {CANONICAL_KEY_CHECK}",
            name="ck_field_correction_override_key",
        ),
        CheckConstraint(
            "(action = 'REVERT' AND override_canonical_key IS NULL AND section_key IS NULL "
            "AND value_type IS NULL AND value_text IS NULL AND value_decimal IS NULL "
            "AND value_integer IS NULL AND value_date IS NULL) OR "
            "(action = 'APPLY' AND value_type IS NOT NULL AND "
            "((override_canonical_key IS NULL AND section_key IS NULL) OR "
            "(override_canonical_key IS NOT NULL AND section_key IS NOT NULL)))",
            name="ck_field_correction_action_shape",
        ),
        CheckConstraint(
            "action = 'REVERT' OR "
            "(value_type IN ('DECIMAL','DAY_COUNT') AND value_decimal IS NOT NULL "
            "AND value_text IS NULL AND value_integer IS NULL AND value_date IS NULL) OR "
            "(value_type = 'INTEGER' AND value_integer IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_date IS NULL) OR "
            "(value_type = 'DATE' AND value_date IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL) OR "
            "(value_type IN ('TEXT','IDENTIFIER') AND value_text IS NOT NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL AND value_date IS NULL)",
            name="ck_field_correction_typed_value",
        ),
        Index(
            "ix_field_correction_org_import", "organization_id", "payroll_import_id",
        ),
        Index(
            "ix_field_correction_review_source", "review_id", "payroll_import_field_id", "revision",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_mapped_field_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[PayrollReviewCorrectionAction] = mapped_column(
        Enum(PayrollReviewCorrectionAction, name="payrollreviewcorrectionaction"), nullable=False,
    )
    supersedes_correction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_import_field_corrections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    adapter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    original_mapping_status: Mapped[PayrollFieldMappingStatus] = mapped_column(
        Enum(PayrollFieldMappingStatus, name="payrollfieldmappingstatus", create_type=False),
        nullable=False,
    )
    original_canonical_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    original_value_type: Mapped[PayrollCanonicalValueType | None] = mapped_column(
        Enum(PayrollCanonicalValueType, name="payrollcanonicalvaluetype", create_type=False),
        nullable=True,
    )
    original_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_value_decimal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    original_value_integer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    override_canonical_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    value_type: Mapped[PayrollCanonicalValueType | None] = mapped_column(
        Enum(PayrollCanonicalValueType, name="payrollcanonicalvaluetype", create_type=False),
        nullable=True,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_decimal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    value_integer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class PayrollImportReviewSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_review_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "payroll_import_id", "organization_id"],
            ["payroll_import_reviews.id", "payroll_import_reviews.payroll_import_id",
             "payroll_import_reviews.organization_id"],
            name="fk_review_snapshot_review_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "review_id", "snapshot_version", name="uq_review_snapshot_version",
        ),
        UniqueConstraint(
            "id", "organization_id", name="uq_review_snapshot_id_org",
        ),
        UniqueConstraint(
            "id", "review_id", "payroll_import_id", "organization_id",
            name="uq_review_snapshot_identity_scope",
        ),
        CheckConstraint("snapshot_version >= 1", name="ck_review_snapshot_version_positive"),
        CheckConstraint("field_count >= 0", name="ck_review_snapshot_field_count"),
        CheckConstraint("issue_count >= 0", name="ck_review_snapshot_issue_count"),
        CheckConstraint(
            "length(source_staging_checksum) = 64 AND length(adapter_output_checksum) = 64 "
            "AND length(review_corrections_checksum) = 64 AND length(snapshot_checksum) = 64",
            name="ck_review_snapshot_checksum_lengths",
        ),
        Index("ix_review_snapshot_org_import", "organization_id", "payroll_import_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    source_staging_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_output_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    review_corrections_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)

    fields = relationship(
        "PayrollImportReviewSnapshotField", back_populates="snapshot",
        cascade="save-update, merge", order_by="PayrollImportReviewSnapshotField.source_import_field_id",
    )


class PayrollImportReviewSnapshotField(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_review_snapshot_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "review_id", "payroll_import_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.review_id",
             "payroll_import_review_snapshots.payroll_import_id",
             "payroll_import_review_snapshots.organization_id"],
            name="fk_snapshot_field_snapshot_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "snapshot_id", "source_import_field_id", name="uq_snapshot_field_source",
        ),
        CheckConstraint(
            f"effective_canonical_key IS NULL OR effective_canonical_key IN {CANONICAL_KEY_CHECK}",
            name="ck_snapshot_field_canonical_key",
        ),
        CheckConstraint(
            "(effective_canonical_key IS NULL AND section_key IS NULL) OR "
            "(effective_canonical_key IS NOT NULL AND section_key IS NOT NULL)",
            name="ck_snapshot_field_canonical_shape",
        ),
        CheckConstraint(
            "(value_type IN ('DECIMAL','DAY_COUNT') AND value_decimal IS NOT NULL "
            "AND value_text IS NULL AND value_integer IS NULL AND value_date IS NULL) OR "
            "(value_type = 'INTEGER' AND value_integer IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_date IS NULL) OR "
            "(value_type = 'DATE' AND value_date IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL) OR "
            "(value_type IN ('TEXT','IDENTIFIER') AND value_text IS NOT NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL AND value_date IS NULL)",
            name="ck_snapshot_field_typed_value",
        ),
        Index("ix_snapshot_field_snapshot", "snapshot_id", "source_import_field_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_import_field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_mapped_field_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_field_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_label: Mapped[str] = mapped_column(String(500), nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_value_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    effective_canonical_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    value_type: Mapped[PayrollCanonicalValueType] = mapped_column(
        Enum(PayrollCanonicalValueType, name="payrollcanonicalvaluetype", create_type=False),
        nullable=False,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_decimal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    value_integer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    provenance: Mapped[PayrollReviewValueProvenance] = mapped_column(
        Enum(PayrollReviewValueProvenance, name="payrollreviewvalueprovenance"), nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    extraction_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_mapping_status: Mapped[PayrollFieldMappingStatus] = mapped_column(
        Enum(PayrollFieldMappingStatus, name="payrollfieldmappingstatus", create_type=False),
        nullable=False,
    )
    review_status: Mapped[PayrollReviewFieldStatus] = mapped_column(
        Enum(PayrollReviewFieldStatus, name="payrollreviewfieldstatus"), nullable=False,
    )
    correction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    adapter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    snapshot = relationship("PayrollImportReviewSnapshot", back_populates="fields")


__all__ = [
    "PayrollImportFieldCorrection", "PayrollImportReview",
    "PayrollImportReviewSnapshot", "PayrollImportReviewSnapshotField",
]
