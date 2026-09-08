"""add generic payroll detail table staging

Revision ID: f1a7c3e9b205
Revises: d9e5f7a1b203
Create Date: 2026-09-08 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f1a7c3e9b205"
down_revision: Union[str, Sequence[str], None] = "d9e5f7a1b203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_import_tables",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_document_id", sa.UUID(), nullable=False),
        sa.Column("source_table_index", sa.Integer(), nullable=False),
        sa.Column("source_table_id", sa.String(200), nullable=False),
        sa.Column("source_label", sa.String(500), nullable=False),
        sa.Column("page_numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "source_table_index >= 0", name="ck_payroll_import_table_source_index",
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_payroll_import_table_row_count"),
        sa.CheckConstraint(
            "column_count >= 0", name="ck_payroll_import_table_column_count",
        ),
        sa.CheckConstraint(
            "length(source_checksum) = 64", name="ck_payroll_import_table_checksum",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_table_import_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_document_id", "payroll_import_id", "organization_id"],
            ["payroll_import_documents.id", "payroll_import_documents.payroll_import_id",
             "payroll_import_documents.organization_id"],
            name="fk_import_table_document_scope", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payroll_import_document_id", "source_table_index",
            name="uq_payroll_import_table_source_position",
        ),
        sa.UniqueConstraint(
            "id", "organization_id", name="uq_payroll_import_table_id_org",
        ),
    )
    op.create_index(
        "ix_payroll_import_table_org_import", "payroll_import_tables",
        ["organization_id", "payroll_import_id", "source_table_index"],
    )

    op.create_table(
        "payroll_import_table_rows",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coordinate_space", sa.String(50), nullable=False),
        sa.Column("extraction_source", sa.String(50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("row_index >= 0", name="ck_payroll_import_table_row_index"),
        sa.CheckConstraint("page_number >= 1", name="ck_payroll_import_table_row_page"),
        sa.ForeignKeyConstraint(
            ["table_id", "organization_id"],
            ["payroll_import_tables.id", "payroll_import_tables.organization_id"],
            name="fk_import_table_row_table_org", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "table_id", "row_index", name="uq_payroll_import_table_row_position",
        ),
        sa.UniqueConstraint(
            "id", "organization_id", name="uq_payroll_import_table_row_id_org",
        ),
    )

    op.create_table(
        "payroll_import_table_cells",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("row_id", sa.UUID(), nullable=False),
        sa.Column("column_index", sa.Integer(), nullable=False),
        sa.Column("source_column_id", sa.String(200), nullable=False),
        sa.Column("column_label", sa.String(500), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(10, 8), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coordinate_space", sa.String(50), nullable=False),
        sa.Column("extraction_source", sa.String(50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "column_index >= 0", name="ck_payroll_import_table_cell_column_index",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_payroll_import_table_cell_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["row_id", "organization_id"],
            ["payroll_import_table_rows.id", "payroll_import_table_rows.organization_id"],
            name="fk_import_table_cell_row_org", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "row_id", "column_index", name="uq_payroll_import_table_cell_position",
        ),
    )


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM payroll_import_tables) THEN
                RAISE EXCEPTION
                    'cannot downgrade while payroll import table evidence exists';
            END IF;
        END $$
    """)
    op.drop_table("payroll_import_table_cells")
    op.drop_table("payroll_import_table_rows")
    op.drop_index(
        "ix_payroll_import_table_org_import", table_name="payroll_import_tables",
    )
    op.drop_table("payroll_import_tables")
