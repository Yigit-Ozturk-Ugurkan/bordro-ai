"""Durable, organization-scoped document import and generic staging models."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    func,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus
from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollFieldMappingScope,
    PayrollFieldMappingStatus,
    PayrollFieldParseStatus,
)


class PayrollImport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_imports"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "content_sha256",
            name="uq_payroll_import_org_content_sha256",
        ),
        UniqueConstraint(
            "id", "organization_id", name="uq_payroll_import_id_org",
        ),
        Index("ix_payroll_import_org_status", "organization_id", "status"),
        Index("ix_payroll_import_org_created", "organization_id", "created_at"),
        CheckConstraint(
            "detected_month IS NULL OR (detected_month >= 1 AND detected_month <= 12)",
            name="ck_payroll_import_detected_month",
        ),
        CheckConstraint(
            "processing_attempt >= 0", name="ck_payroll_import_processing_attempt",
        ),
        CheckConstraint(
            "template_match_score IS NULL OR "
            "(template_match_score >= 0 AND template_match_score <= 1)",
            name="ck_payroll_import_template_match_score",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[PayrollImportStatus] = mapped_column(
        Enum(PayrollImportStatus, name="payrollimportstatus"), nullable=False,
        default=PayrollImportStatus.UPLOADED,
    )
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="DOCUMENT_UPLOAD"
    )
    reader_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="GENERAL_READER"
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    detected_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    detected_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    template_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template_match_score: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 8), nullable=True
    )
    extraction_schema_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    reader_table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reader_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    processing_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    documents = relationship(
        "PayrollImportDocument", back_populates="payroll_import",
        cascade="all, delete-orphan",
    )
    fields = relationship(
        "PayrollImportField", back_populates="payroll_import",
        cascade="all, delete-orphan", overlaps="document,fields",
    )
    mapped_fields = relationship(
        "PayrollImportMappedField", back_populates="payroll_import",
        cascade="all, delete-orphan", overlaps="mapped_result,source_field",
    )
    mapping_issues = relationship(
        "PayrollImportMappingIssue", back_populates="payroll_import",
        cascade="all, delete-orphan",
    )


class PayrollImportDocument(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_documents"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_payroll_import_document_file_id"),
        UniqueConstraint("storage_key", name="uq_payroll_import_document_storage_key"),
        UniqueConstraint(
            "id", "payroll_import_id", "organization_id",
            name="uq_payroll_import_document_identity_scope",
        ),
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            ondelete="CASCADE", name="fk_import_document_import_org",
        ),
        Index(
            "ix_payroll_import_document_org_import",
            "organization_id", "payroll_import_id",
        ),
        CheckConstraint("size_bytes > 0", name="ck_import_document_size_positive"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reader_document_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payroll_import = relationship("PayrollImport", back_populates="documents")
    fields = relationship(
        "PayrollImportField", back_populates="document",
        cascade="all, delete-orphan", overlaps="fields,payroll_import",
    )


class PayrollImportField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_import_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            ondelete="CASCADE", name="fk_import_field_import_org",
        ),
        ForeignKeyConstraint(
            ["payroll_import_document_id", "payroll_import_id", "organization_id"],
            ["payroll_import_documents.id", "payroll_import_documents.payroll_import_id",
             "payroll_import_documents.organization_id"],
            ondelete="CASCADE", name="fk_import_field_document_scope",
        ),
        UniqueConstraint(
            "payroll_import_document_id", "source_field_id", "page_number",
            name="uq_payroll_import_field_source_page",
        ),
        Index(
            "ix_payroll_import_field_org_import",
            "organization_id", "payroll_import_id",
        ),
        Index(
            "ix_payroll_import_field_import_source",
            "payroll_import_id", "source_field_id",
        ),
        Index(
            "uq_payroll_import_field_mapping_scope",
            "id", "payroll_import_id", "organization_id", unique=True,
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_payroll_import_field_confidence",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    source_field_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_label: Mapped[str] = mapped_column(String(500), nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    coordinate_space: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extraction_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rule_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    missing_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_status: Mapped[PayrollImportFieldReviewStatus] = mapped_column(
        Enum(PayrollImportFieldReviewStatus, name="payrollimportfieldreviewstatus"),
        nullable=False,
    )

    payroll_import = relationship(
        "PayrollImport", back_populates="fields", overlaps="document,fields"
    )
    document = relationship(
        "PayrollImportDocument", back_populates="fields",
        overlaps="fields,payroll_import",
    )
    mapped_result = relationship(
        "PayrollImportMappedField", back_populates="source_field", uselist=False,
        overlaps="mapped_fields,payroll_import",
    )


class PayrollFieldMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Auditable PostgreSQL mapping configuration; never inferred by the adapter."""

    __tablename__ = "payroll_field_mappings"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_payroll_field_mapping_priority"),
        CheckConstraint("version >= 1", name="ck_payroll_field_mapping_version"),
        CheckConstraint(
            "(scope = 'SYSTEM' AND organization_id IS NULL "
            "AND template_provider IS NULL AND template_external_id IS NULL) OR "
            "(scope = 'ORGANIZATION' AND organization_id IS NOT NULL "
            "AND template_provider IS NULL AND template_external_id IS NULL) OR "
            "(scope = 'TEMPLATE' AND organization_id IS NOT NULL "
            "AND template_provider IS NOT NULL AND template_external_id IS NOT NULL)",
            name="ck_payroll_field_mapping_scope_shape",
        ),
        CheckConstraint(
            "canonical_key IN ('employee_identifier','period_year','period_month',"
            "'gross_earnings','sgk_base','income_tax_base','stamp_tax_base',"
            "'employee_sgk','employee_unemployment','income_tax','stamp_tax',"
            "'total_earnings','total_deductions','net_pay','paid_days','missing_days',"
            "'cumulative_income_tax_base')",
            name="ck_payroll_field_mapping_canonical_key",
        ),
        Index(
            "ix_payroll_field_mapping_system_label", "source_label_normalized",
            "is_active", postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "ix_payroll_field_mapping_org_label", "organization_id",
            "source_label_normalized", "is_active",
        ),
        Index(
            "ix_payroll_field_mapping_template", "organization_id",
            "template_provider", "template_external_id", "source_label_normalized",
            "is_active",
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[PayrollFieldMappingScope] = mapped_column(
        Enum(PayrollFieldMappingScope, name="payrollfieldmappingscope"), nullable=False
    )
    template_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_field_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_label_normalized: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(100), nullable=False)
    section_key: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value_type: Mapped[PayrollCanonicalValueType] = mapped_column(
        Enum(PayrollCanonicalValueType, name="payrollcanonicalvaluetype"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PayrollImportMappedField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Replaceable adapter output for one immutable generic staging field."""

    __tablename__ = "payroll_import_mapped_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_mapped_field_import_org", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["payroll_import_field_id", "payroll_import_id", "organization_id"],
            ["payroll_import_fields.id", "payroll_import_fields.payroll_import_id",
             "payroll_import_fields.organization_id"],
            name="fk_mapped_field_source_scope", ondelete="CASCADE",
        ),
        UniqueConstraint(
            "payroll_import_field_id", name="uq_payroll_import_mapped_source_field"
        ),
        CheckConstraint(
            "canonical_key IS NULL OR canonical_key IN ('employee_identifier','period_year',"
            "'period_month','gross_earnings','sgk_base','income_tax_base','stamp_tax_base',"
            "'employee_sgk','employee_unemployment','income_tax','stamp_tax',"
            "'total_earnings','total_deductions','net_pay','paid_days','missing_days',"
            "'cumulative_income_tax_base')",
            name="ck_payroll_import_mapped_canonical_key",
        ),
        CheckConstraint(
            "(mapping_status IN ('UNMAPPED','AMBIGUOUS') AND canonical_key IS NULL "
            "AND section_key IS NULL AND mapping_id IS NULL AND mapping_version IS NULL "
            "AND target_value_type IS NULL AND parse_status = 'NOT_APPLICABLE' "
            "AND value_text IS NULL AND value_decimal IS NULL AND value_integer IS NULL "
            "AND value_date IS NULL) OR (mapping_status = 'PARSE_FAILED' "
            "AND canonical_key IS NOT NULL AND section_key IS NOT NULL AND mapping_id IS NOT NULL "
            "AND mapping_version IS NOT NULL AND target_value_type IS NOT NULL "
            "AND parse_status = 'FAILED' AND value_text IS NULL AND value_decimal IS NULL "
            "AND value_integer IS NULL AND value_date IS NULL) OR (mapping_status = 'MAPPED' "
            "AND canonical_key IS NOT NULL AND section_key IS NOT NULL AND mapping_id IS NOT NULL "
            "AND mapping_version IS NOT NULL AND target_value_type IS NOT NULL "
            "AND parse_status = 'PARSED')",
            name="ck_payroll_import_mapped_status_shape",
        ),
        CheckConstraint(
            "parse_status <> 'PARSED' OR "
            "(target_value_type IN ('DECIMAL','DAY_COUNT') AND value_decimal IS NOT NULL "
            "AND value_text IS NULL AND value_integer IS NULL AND value_date IS NULL) OR "
            "(target_value_type = 'INTEGER' AND value_integer IS NOT NULL "
            "AND value_text IS NULL AND value_decimal IS NULL AND value_date IS NULL) OR "
            "(target_value_type = 'DATE' AND value_date IS NOT NULL "
            "AND value_text IS NULL AND value_decimal IS NULL AND value_integer IS NULL) OR "
            "(target_value_type IN ('TEXT','IDENTIFIER') AND value_text IS NOT NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL AND value_date IS NULL)",
            name="ck_payroll_import_mapped_typed_value",
        ),
        Index("ix_payroll_import_mapped_org_import", "organization_id", "payroll_import_id"),
        Index("ix_payroll_import_mapped_import_status", "payroll_import_id", "mapping_status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    canonical_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_field_mappings.id", ondelete="RESTRICT"), nullable=True
    )
    mapping_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_value_type: Mapped[PayrollCanonicalValueType | None] = mapped_column(
        Enum(PayrollCanonicalValueType, name="payrollcanonicalvaluetype", create_type=False),
        nullable=True,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_decimal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    value_integer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    candidate_canonical_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    mapping_status: Mapped[PayrollFieldMappingStatus] = mapped_column(
        Enum(PayrollFieldMappingStatus, name="payrollfieldmappingstatus"), nullable=False
    )
    parse_status: Mapped[PayrollFieldParseStatus] = mapped_column(
        Enum(PayrollFieldParseStatus, name="payrollfieldparsestatus"), nullable=False
    )
    review_status: Mapped[PayrollImportFieldReviewStatus] = mapped_column(
        Enum(PayrollImportFieldReviewStatus, name="payrollimportfieldreviewstatus", create_type=False),
        nullable=False,
    )
    review_reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    payroll_import = relationship(
        "PayrollImport", back_populates="mapped_fields", overlaps="mapped_result,source_field"
    )
    source_field = relationship(
        "PayrollImportField", back_populates="mapped_result", overlaps="mapped_fields,payroll_import"
    )
    mapping = relationship("PayrollFieldMapping")


class PayrollImportMappingIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A required canonical concept absent from the current adapter snapshot."""

    __tablename__ = "payroll_import_mapping_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_mapping_issue_import_org", ondelete="CASCADE",
        ),
        UniqueConstraint(
            "payroll_import_id", "canonical_key", name="uq_mapping_issue_import_key"
        ),
        CheckConstraint(
            "canonical_key IN ('employee_identifier','period_year','period_month',"
            "'gross_earnings','sgk_base','income_tax_base','stamp_tax_base',"
            "'employee_sgk','employee_unemployment','income_tax','stamp_tax',"
            "'total_earnings','total_deductions','net_pay','paid_days','missing_days',"
            "'cumulative_income_tax_base')",
            name="ck_payroll_import_mapping_issue_canonical_key",
        ),
        Index("ix_mapping_issue_org_import", "organization_id", "payroll_import_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(100), nullable=False)
    section_key: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value_type: Mapped[PayrollCanonicalValueType] = mapped_column(
        Enum(PayrollCanonicalValueType, name="payrollcanonicalvaluetype", create_type=False),
        nullable=False,
    )
    issue_code: Mapped[str] = mapped_column(String(80), nullable=False)
    review_status: Mapped[PayrollImportFieldReviewStatus] = mapped_column(
        Enum(PayrollImportFieldReviewStatus, name="payrollimportfieldreviewstatus", create_type=False),
        nullable=False,
    )

    payroll_import = relationship("PayrollImport", back_populates="mapping_issues")
