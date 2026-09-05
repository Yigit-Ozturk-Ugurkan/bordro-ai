"""add payroll adapter mapping and canonical review tables

Revision ID: c8b2e4f6a012
Revises: b7a1d3e5f901
Create Date: 2026-09-05 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c8b2e4f6a012"
down_revision: Union[str, Sequence[str], None] = "b7a1d3e5f901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

mapping_scope = postgresql.ENUM(
    "SYSTEM", "ORGANIZATION", "TEMPLATE", name="payrollfieldmappingscope",
    create_type=False,
)
value_type = postgresql.ENUM(
    "DECIMAL", "INTEGER", "DAY_COUNT", "DATE", "TEXT", "IDENTIFIER",
    name="payrollcanonicalvaluetype", create_type=False,
)
mapping_status = postgresql.ENUM(
    "MAPPED", "UNMAPPED", "AMBIGUOUS", "PARSE_FAILED",
    name="payrollfieldmappingstatus", create_type=False,
)
parse_status = postgresql.ENUM(
    "PARSED", "NOT_APPLICABLE", "FAILED", name="payrollfieldparsestatus",
    create_type=False,
)

KEY_CHECK = (
    "('employee_identifier','period_year','period_month','gross_earnings','sgk_base',"
    "'income_tax_base','stamp_tax_base','employee_sgk','employee_unemployment',"
    "'income_tax','stamp_tax','total_earnings','total_deductions','net_pay','paid_days',"
    "'missing_days','cumulative_income_tax_base')"
)


def upgrade() -> None:
    bind = op.get_bind()
    mapping_scope.create(bind, checkfirst=True)
    value_type.create(bind, checkfirst=True)
    mapping_status.create(bind, checkfirst=True)
    parse_status.create(bind, checkfirst=True)

    op.create_index(
        "uq_payroll_import_field_mapping_scope", "payroll_import_fields",
        ["id", "payroll_import_id", "organization_id"], unique=True,
    )
    op.create_table(
        "payroll_field_mappings",
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("scope", mapping_scope, nullable=False),
        sa.Column("template_provider", sa.String(50), nullable=True),
        sa.Column("template_external_id", sa.String(100), nullable=True),
        sa.Column("source_field_id", sa.String(200), nullable=True),
        sa.Column("source_label_normalized", sa.String(500), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=False),
        sa.Column("section_key", sa.String(50), nullable=False),
        sa.Column("target_value_type", value_type, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("priority >= 0", name="ck_payroll_field_mapping_priority"),
        sa.CheckConstraint("version >= 1", name="ck_payroll_field_mapping_version"),
        sa.CheckConstraint(
            "(scope = 'SYSTEM' AND organization_id IS NULL AND template_provider IS NULL "
            "AND template_external_id IS NULL) OR (scope = 'ORGANIZATION' AND "
            "organization_id IS NOT NULL AND template_provider IS NULL AND "
            "template_external_id IS NULL) OR (scope = 'TEMPLATE' AND organization_id "
            "IS NOT NULL AND template_provider IS NOT NULL AND template_external_id IS NOT NULL)",
            name="ck_payroll_field_mapping_scope_shape",
        ),
        sa.CheckConstraint(f"canonical_key IN {KEY_CHECK}", name="ck_payroll_field_mapping_canonical_key"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payroll_field_mapping_system_label", "payroll_field_mappings",
        ["source_label_normalized", "is_active"],
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "ix_payroll_field_mapping_org_label", "payroll_field_mappings",
        ["organization_id", "source_label_normalized", "is_active"],
    )
    op.create_index(
        "ix_payroll_field_mapping_template", "payroll_field_mappings",
        ["organization_id", "template_provider", "template_external_id",
         "source_label_normalized", "is_active"],
    )

    op.create_table(
        "payroll_import_mapped_fields",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_field_id", sa.UUID(), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=True),
        sa.Column("section_key", sa.String(50), nullable=True),
        sa.Column("mapping_id", sa.UUID(), nullable=True),
        sa.Column("mapping_version", sa.Integer(), nullable=True),
        sa.Column("target_value_type", value_type, nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_decimal", sa.Numeric(18, 2), nullable=True),
        sa.Column("value_integer", sa.Integer(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("candidate_canonical_keys", postgresql.JSONB(), nullable=False),
        sa.Column("mapping_status", mapping_status, nullable=False),
        sa.Column("parse_status", parse_status, nullable=False),
        sa.Column("review_status", postgresql.ENUM(name="payrollimportfieldreviewstatus", create_type=False), nullable=False),
        sa.Column("review_reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"canonical_key IS NULL OR canonical_key IN {KEY_CHECK}",
            name="ck_payroll_import_mapped_canonical_key",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_mapped_field_import_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_field_id", "payroll_import_id", "organization_id"],
            ["payroll_import_fields.id", "payroll_import_fields.payroll_import_id",
             "payroll_import_fields.organization_id"],
            name="fk_mapped_field_source_scope", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["mapping_id"], ["payroll_field_mappings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_import_field_id", name="uq_payroll_import_mapped_source_field"),
    )
    op.create_index("ix_payroll_import_mapped_org_import", "payroll_import_mapped_fields", ["organization_id", "payroll_import_id"])
    op.create_index("ix_payroll_import_mapped_import_status", "payroll_import_mapped_fields", ["payroll_import_id", "mapping_status"])

    op.create_table(
        "payroll_import_mapping_issues",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=False),
        sa.Column("section_key", sa.String(50), nullable=False),
        sa.Column("target_value_type", value_type, nullable=False),
        sa.Column("issue_code", sa.String(80), nullable=False),
        sa.Column("review_status", postgresql.ENUM(name="payrollimportfieldreviewstatus", create_type=False), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"canonical_key IN {KEY_CHECK}",
            name="ck_payroll_import_mapping_issue_canonical_key",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_mapping_issue_import_org", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_import_id", "canonical_key", name="uq_mapping_issue_import_key"),
    )
    op.create_index("ix_mapping_issue_org_import", "payroll_import_mapping_issues", ["organization_id", "payroll_import_id"])

    # Deliberately small, explicit aliases only. Abbreviations such as "Dev." are absent.
    aliases = [
        ("21000000-0000-0000-0000-000000000001", "personel no", "employee_identifier", "IDENTITY", "IDENTIFIER"),
        ("21000000-0000-0000-0000-000000000002", "dönem yılı", "period_year", "PERIOD", "INTEGER"),
        ("21000000-0000-0000-0000-000000000003", "dönem ayı", "period_month", "PERIOD", "INTEGER"),
        ("21000000-0000-0000-0000-000000000004", "brüt kazanç", "gross_earnings", "EARNINGS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000005", "sgk matrahı", "sgk_base", "BASES", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000006", "gelir vergisi matrahı", "income_tax_base", "BASES", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000007", "damga vergisi matrahı", "stamp_tax_base", "BASES", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000008", "sgk işçi payı", "employee_sgk", "DEDUCTIONS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000009", "işsizlik sigortası işçi payı", "employee_unemployment", "DEDUCTIONS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000010", "gelir vergisi", "income_tax", "DEDUCTIONS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000011", "damga vergisi", "stamp_tax", "DEDUCTIONS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000012", "toplam kazanç", "total_earnings", "TOTALS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000013", "toplam kesinti", "total_deductions", "TOTALS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000014", "net ücret", "net_pay", "TOTALS", "DECIMAL"),
        ("21000000-0000-0000-0000-000000000015", "prim ödeme gün sayısı", "paid_days", "ATTENDANCE", "DAY_COUNT"),
        ("21000000-0000-0000-0000-000000000016", "eksik gün", "missing_days", "ATTENDANCE", "DAY_COUNT"),
        ("21000000-0000-0000-0000-000000000017", "kümülatif gelir vergisi matrahı", "cumulative_income_tax_base", "TAX_CONTEXT", "DECIMAL"),
    ]
    table = sa.table(
        "payroll_field_mappings",
        sa.column("id", sa.UUID()), sa.column("scope", mapping_scope),
        sa.column("source_label_normalized", sa.String()), sa.column("canonical_key", sa.String()),
        sa.column("section_key", sa.String()), sa.column("target_value_type", value_type),
        sa.column("priority", sa.Integer()), sa.column("version", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(table, [dict(
        id=id_, scope="SYSTEM", source_label_normalized=label,
        canonical_key=key, section_key=section, target_value_type=kind,
        priority=0, version=1, is_active=True,
    ) for id_, label, key, section, kind in aliases])


def downgrade() -> None:
    op.drop_index("ix_mapping_issue_org_import", table_name="payroll_import_mapping_issues")
    op.drop_table("payroll_import_mapping_issues")
    op.drop_index("ix_payroll_import_mapped_import_status", table_name="payroll_import_mapped_fields")
    op.drop_index("ix_payroll_import_mapped_org_import", table_name="payroll_import_mapped_fields")
    op.drop_table("payroll_import_mapped_fields")
    op.drop_index("ix_payroll_field_mapping_template", table_name="payroll_field_mappings")
    op.drop_index("ix_payroll_field_mapping_org_label", table_name="payroll_field_mappings")
    op.drop_index("ix_payroll_field_mapping_system_label", table_name="payroll_field_mappings")
    op.drop_table("payroll_field_mappings")
    op.drop_index("uq_payroll_import_field_mapping_scope", table_name="payroll_import_fields")
    parse_status.drop(op.get_bind(), checkfirst=True)
    mapping_status.drop(op.get_bind(), checkfirst=True)
    value_type.drop(op.get_bind(), checkfirst=True)
    mapping_scope.drop(op.get_bind(), checkfirst=True)
