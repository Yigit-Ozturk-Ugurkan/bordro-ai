"""add payroll import and generic extraction staging

Revision ID: b7a1d3e5f901
Revises: d2f4e6a8b1c3
Create Date: 2026-09-05 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7a1d3e5f901"
down_revision: Union[str, Sequence[str], None] = "d2f4e6a8b1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


payroll_import_status = postgresql.ENUM(
    "UPLOADED", "PROCESSING", "EXTRACTED", "REVIEW_REQUIRED", "FAILED",
    "REJECTED", name="payrollimportstatus", create_type=False,
)
field_review_status = postgresql.ENUM(
    "UNREVIEWED", "REVIEW_REQUIRED", "MISSING",
    name="payrollimportfieldreviewstatus", create_type=False,
)


def upgrade() -> None:
    payroll_import_status.create(op.get_bind(), checkfirst=True)
    field_review_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payroll_imports",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=False),
        sa.Column("status", payroll_import_status, nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("reader_provider", sa.String(length=50), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("detected_employee_id", sa.UUID(), nullable=True),
        sa.Column("detected_year", sa.Integer(), nullable=True),
        sa.Column("detected_month", sa.Integer(), nullable=True),
        sa.Column("template_external_id", sa.String(length=100), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("template_scope", sa.String(length=50), nullable=True),
        sa.Column("template_match_score", sa.Numeric(10, 8), nullable=True),
        sa.Column("extraction_schema_version", sa.String(length=20), nullable=True),
        sa.Column("reader_table_count", sa.Integer(), nullable=False),
        sa.Column("reader_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_attempt", sa.Integer(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "detected_month IS NULL OR (detected_month >= 1 AND detected_month <= 12)",
            name="ck_payroll_import_detected_month",
        ),
        sa.CheckConstraint(
            "processing_attempt >= 0", name="ck_payroll_import_processing_attempt",
        ),
        sa.CheckConstraint(
            "template_match_score IS NULL OR "
            "(template_match_score >= 0 AND template_match_score <= 1)",
            name="ck_payroll_import_template_match_score",
        ),
        sa.ForeignKeyConstraint(
            ["detected_employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "content_sha256",
            name="uq_payroll_import_org_content_sha256",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_payroll_import_id_org"),
    )
    op.create_index(
        "ix_payroll_import_org_status", "payroll_imports",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_payroll_import_org_created", "payroll_imports",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "payroll_import_documents",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("declared_mime_type", sa.String(length=100), nullable=False),
        sa.Column("detected_mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_provider", sa.String(length=30), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("reader_document_id", sa.String(length=100), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_import_document_size_positive"),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_document_import_org", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", name="uq_payroll_import_document_file_id"),
        sa.UniqueConstraint("storage_key", name="uq_payroll_import_document_storage_key"),
        sa.UniqueConstraint(
            "id", "payroll_import_id", "organization_id",
            name="uq_payroll_import_document_identity_scope",
        ),
    )
    op.create_index(
        "ix_payroll_import_document_org_import", "payroll_import_documents",
        ["organization_id", "payroll_import_id"],
    )

    op.create_table(
        "payroll_import_fields",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_document_id", sa.UUID(), nullable=False),
        sa.Column("source_field_id", sa.String(length=200), nullable=False),
        sa.Column("source_label", sa.String(length=500), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Numeric(10, 8), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coordinate_space", sa.String(length=50), nullable=True),
        sa.Column("extraction_source", sa.String(length=50), nullable=True),
        sa.Column("rule_index", sa.Integer(), nullable=True),
        sa.Column("missing_reason_code", sa.String(length=80), nullable=True),
        sa.Column("missing_reason", sa.String(length=500), nullable=True),
        sa.Column("review_status", field_review_status, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_payroll_import_field_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_field_import_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_document_id", "payroll_import_id", "organization_id"],
            ["payroll_import_documents.id", "payroll_import_documents.payroll_import_id",
             "payroll_import_documents.organization_id"],
            name="fk_import_field_document_scope", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payroll_import_document_id", "source_field_id", "page_number",
            name="uq_payroll_import_field_source_page",
        ),
    )
    op.create_index(
        "ix_payroll_import_field_org_import", "payroll_import_fields",
        ["organization_id", "payroll_import_id"],
    )
    op.create_index(
        "ix_payroll_import_field_import_source", "payroll_import_fields",
        ["payroll_import_id", "source_field_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_import_field_import_source", table_name="payroll_import_fields")
    op.drop_index("ix_payroll_import_field_org_import", table_name="payroll_import_fields")
    op.drop_table("payroll_import_fields")
    op.drop_index(
        "ix_payroll_import_document_org_import", table_name="payroll_import_documents"
    )
    op.drop_table("payroll_import_documents")
    op.drop_index("ix_payroll_import_org_created", table_name="payroll_imports")
    op.drop_index("ix_payroll_import_org_status", table_name="payroll_imports")
    op.drop_table("payroll_imports")
    field_review_status.drop(op.get_bind(), checkfirst=True)
    payroll_import_status.drop(op.get_bind(), checkfirst=True)
