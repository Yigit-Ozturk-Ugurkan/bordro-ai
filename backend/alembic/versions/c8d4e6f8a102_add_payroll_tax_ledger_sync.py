"""add revision-aware payroll tax ledger synchronization

Revision ID: c8d4e6f8a102
Revises: b7c2d9e4f610
Create Date: 2026-09-07 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d4e6f8a102"
down_revision: Union[str, Sequence[str], None] = "b7c2d9e4f610"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_materialization_tax_sync_scope", "payroll_import_materializations",
        ["id", "organization_id", "payroll_id", "payroll_version_id"],
    )

    op.add_column(
        "tax_calculation_runs",
        sa.Column("payroll_version_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tax_calc_run_payroll_version", "tax_calculation_runs",
        "payroll_versions", ["payroll_version_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_tax_calc_runs_payroll_version_id", "tax_calculation_runs",
        ["payroll_version_id"],
    )
    op.create_unique_constraint(
        "uq_tax_calc_run_sync_scope", "tax_calculation_runs",
        ["id", "organization_id", "employee_id", "tax_year", "rule_set_id",
         "payroll_version_id"],
    )

    op.add_column(
        "tax_cumulative_records",
        sa.Column(
            "is_current", sa.Boolean(), server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "tax_cumulative_records",
        sa.Column("supersedes_record_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tax_cumulative_supersedes", "tax_cumulative_records",
        "tax_cumulative_records", ["supersedes_record_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_tax_cumulative_supersedes_record", "tax_cumulative_records",
        ["supersedes_record_id"],
    )
    op.create_unique_constraint(
        "uq_tax_cumulative_sync_scope", "tax_cumulative_records",
        ["id", "calculation_run_id", "employee_id", "payroll_version_id",
         "tax_year", "period_month"],
    )
    op.create_index(
        "uq_tax_cumulative_current_period", "tax_cumulative_records",
        ["employee_id", "tax_year", "period_month"], unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "payroll_tax_ledger_syncs",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("materialization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_id", sa.UUID(), nullable=False),
        sa.Column("payroll_version_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("tax_calculation_run_id", sa.UUID(), nullable=False),
        sa.Column("tax_cumulative_record_id", sa.UUID(), nullable=False),
        sa.Column("prior_sync_id", sa.UUID(), nullable=True),
        sa.Column("supersedes_sync_id", sa.UUID(), nullable=True),
        sa.Column("ruleset_id", sa.UUID(), nullable=False),
        sa.Column("ruleset_version", sa.String(100), nullable=False),
        sa.Column("payroll_source_checksum", sa.String(64), nullable=False),
        sa.Column("result_checksum", sa.String(64), nullable=False),
        sa.Column("reconciliation_status", sa.String(20), nullable=False),
        sa.Column(
            "is_current", sa.Boolean(), server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("synced_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("tax_year >= 2000", name="ck_tax_sync_year_valid"),
        sa.CheckConstraint(
            "period_year = tax_year", name="ck_tax_sync_period_tax_year",
        ),
        sa.CheckConstraint(
            "period_month >= 1 AND period_month <= 12",
            name="ck_tax_sync_period_month_valid",
        ),
        sa.CheckConstraint(
            "length(payroll_source_checksum) = 64",
            name="ck_tax_sync_payroll_checksum",
        ),
        sa.CheckConstraint(
            "length(result_checksum) = 64", name="ck_tax_sync_result_checksum",
        ),
        sa.CheckConstraint(
            "reconciliation_status = 'MATCHED'",
            name="ck_tax_sync_reconciliation_matched",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id"], ["payroll_imports.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_id"], ["payrolls.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_version_id"], ["payroll_versions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ruleset_id"], ["tax_rule_sets.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["synced_by_user_id"], ["users.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_sync_id"], ["payroll_tax_ledger_syncs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_sync_id"], ["payroll_tax_ledger_syncs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["materialization_id", "organization_id", "payroll_id",
             "payroll_version_id"],
            ["payroll_import_materializations.id",
             "payroll_import_materializations.organization_id",
             "payroll_import_materializations.payroll_id",
             "payroll_import_materializations.payroll_version_id"],
            name="fk_tax_sync_materialization_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tax_calculation_run_id", "organization_id", "employee_id",
             "tax_year", "ruleset_id", "payroll_version_id"],
            ["tax_calculation_runs.id", "tax_calculation_runs.organization_id",
             "tax_calculation_runs.employee_id", "tax_calculation_runs.tax_year",
             "tax_calculation_runs.rule_set_id",
             "tax_calculation_runs.payroll_version_id"],
            name="fk_tax_sync_calculation_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "materialization_id", name="uq_tax_sync_materialization",
        ),
        sa.UniqueConstraint(
            "payroll_version_id", name="uq_tax_sync_payroll_version",
        ),
        sa.UniqueConstraint(
            "tax_calculation_run_id", name="uq_tax_sync_calculation_run",
        ),
        sa.UniqueConstraint(
            "tax_cumulative_record_id", name="uq_tax_sync_cumulative_record",
        ),
        sa.UniqueConstraint(
            "supersedes_sync_id", name="uq_tax_sync_supersedes",
        ),
    )
    op.create_index(
        "ix_tax_sync_org_import", "payroll_tax_ledger_syncs",
        ["organization_id", "payroll_import_id"],
    )
    op.create_index(
        "ix_tax_sync_employee_year_period", "payroll_tax_ledger_syncs",
        ["organization_id", "employee_id", "tax_year", "period_month"],
    )
    op.create_index(
        "uq_tax_sync_current_period", "payroll_tax_ledger_syncs",
        ["organization_id", "employee_id", "tax_year", "period_month"],
        unique=True, postgresql_where=sa.text("is_current = true"),
    )

    op.execute("""
        CREATE FUNCTION enforce_payroll_tax_sync() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'payroll tax sync evidence is immutable';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.is_current AND NOT NEW.is_current
                   AND (to_jsonb(NEW) - 'is_current') =
                       (to_jsonb(OLD) - 'is_current') THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'payroll tax sync evidence is immutable';
            END IF;
            IF NOT NEW.is_current THEN
                RAISE EXCEPTION 'new payroll tax sync must be current';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM payroll_import_materializations materialization
                  JOIN payroll_import_approvals approval
                    ON approval.id = materialization.approval_id
                  JOIN payroll_versions version
                    ON version.id = materialization.payroll_version_id
                  JOIN payrolls payroll ON payroll.id = version.payroll_id
                 WHERE materialization.id = NEW.materialization_id
                   AND materialization.organization_id = NEW.organization_id
                   AND materialization.payroll_import_id = NEW.payroll_import_id
                   AND materialization.payroll_id = NEW.payroll_id
                   AND materialization.payroll_version_id = NEW.payroll_version_id
                   AND materialization.snapshot_checksum = NEW.payroll_source_checksum
                   AND approval.decision = 'APPROVED'
                   AND approval.payroll_import_id = NEW.payroll_import_id
                   AND approval.organization_id = NEW.organization_id
                   AND version.source_import_id = NEW.payroll_import_id
                   AND version.source_checksum = NEW.payroll_source_checksum
                   AND version.status = 'ACTIVE'
                   AND version.is_current
                   AND version.income_tax_base = (
                       SELECT monthly_taxable_base FROM tax_cumulative_records
                        WHERE id = NEW.tax_cumulative_record_id
                   )
                   AND version.income_tax = (
                       SELECT withholding_tax FROM tax_cumulative_records
                        WHERE id = NEW.tax_cumulative_record_id
                   )
                   AND payroll.id = NEW.payroll_id
                   AND payroll.organization_id = NEW.organization_id
                   AND payroll.employee_id = NEW.employee_id
                   AND payroll.period_year = NEW.period_year
                   AND payroll.period_month = NEW.period_month
            ) THEN
                RAISE EXCEPTION 'payroll tax sync provenance is invalid';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM tax_calculation_runs run
                  JOIN tax_rule_sets ruleset ON ruleset.id = run.rule_set_id
                 WHERE run.id = NEW.tax_calculation_run_id
                   AND run.organization_id = NEW.organization_id
                   AND run.employee_id = NEW.employee_id
                   AND run.tax_year = NEW.tax_year
                   AND run.rule_set_id = NEW.ruleset_id
                   AND run.payroll_version_id = NEW.payroll_version_id
                   AND run.status = 'COMPLETED'
                   AND ruleset.version = NEW.ruleset_version
            ) THEN
                RAISE EXCEPTION 'payroll tax calculation provenance is invalid';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM tax_cumulative_records record
                 WHERE record.id = NEW.tax_cumulative_record_id
                   AND record.calculation_run_id = NEW.tax_calculation_run_id
                   AND record.employee_id = NEW.employee_id
                   AND record.payroll_version_id = NEW.payroll_version_id
                   AND record.tax_year = NEW.tax_year
                   AND record.period_month = NEW.period_month
                   AND record.is_current
            ) THEN
                RAISE EXCEPTION 'payroll tax cumulative provenance is invalid';
            END IF;
            IF NEW.supersedes_sync_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                  FROM payroll_tax_ledger_syncs old_sync
                  JOIN tax_cumulative_records new_record
                    ON new_record.id = NEW.tax_cumulative_record_id
                 WHERE old_sync.id = NEW.supersedes_sync_id
                   AND old_sync.organization_id = NEW.organization_id
                   AND old_sync.employee_id = NEW.employee_id
                   AND old_sync.tax_year = NEW.tax_year
                   AND old_sync.period_month = NEW.period_month
                   AND old_sync.payroll_version_id <> NEW.payroll_version_id
                   AND NOT old_sync.is_current
                   AND new_record.supersedes_record_id =
                       old_sync.tax_cumulative_record_id
            ) THEN
                RAISE EXCEPTION 'payroll tax supersession lineage is invalid';
            END IF;
            IF NEW.supersedes_sync_id IS NULL AND EXISTS (
                SELECT 1 FROM payroll_tax_ledger_syncs old_sync
                 WHERE old_sync.organization_id = NEW.organization_id
                   AND old_sync.employee_id = NEW.employee_id
                   AND old_sync.tax_year = NEW.tax_year
                   AND old_sync.period_month = NEW.period_month
                   AND old_sync.payroll_version_id <> NEW.payroll_version_id
            ) THEN
                RAISE EXCEPTION 'payroll tax supersession lineage is required';
            END IF;
            IF NEW.prior_sync_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                  FROM payroll_tax_ledger_syncs prior_sync
                  JOIN tax_cumulative_records prior_record
                    ON prior_record.id = prior_sync.tax_cumulative_record_id
                  JOIN tax_cumulative_records new_record
                    ON new_record.id = NEW.tax_cumulative_record_id
                 WHERE prior_sync.id = NEW.prior_sync_id
                   AND prior_sync.organization_id = NEW.organization_id
                   AND prior_sync.employee_id = NEW.employee_id
                   AND prior_sync.tax_year = NEW.tax_year
                   AND prior_sync.period_month < NEW.period_month
                   AND prior_sync.is_current
                   AND prior_record.is_current
                   AND new_record.opening_cumulative_base =
                       prior_record.closing_cumulative_base
            ) THEN
                RAISE EXCEPTION 'payroll tax prior-period lineage is invalid';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_payroll_tax_sync_integrity
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_tax_ledger_syncs
        FOR EACH ROW EXECUTE FUNCTION enforce_payroll_tax_sync()
    """)
    op.execute("""
        CREATE FUNCTION protect_synced_tax_record() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND pg_trigger_depth() > 1
               AND OLD.is_current AND NOT NEW.is_current
               AND (to_jsonb(NEW) - 'is_current') =
                   (to_jsonb(OLD) - 'is_current') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'synchronized tax cumulative evidence is immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_synced_tax_record_immutable
        BEFORE UPDATE OR DELETE ON tax_cumulative_records
        FOR EACH ROW EXECUTE FUNCTION protect_synced_tax_record()
    """)
    op.execute("""
        CREATE FUNCTION protect_synced_tax_run() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'synchronized tax calculation evidence is immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_synced_tax_run_immutable
        BEFORE UPDATE OR DELETE ON tax_calculation_runs
        FOR EACH ROW EXECUTE FUNCTION protect_synced_tax_run()
    """)
    op.execute("""
        CREATE FUNCTION demote_superseded_tax_record() RETURNS trigger AS $$
        BEGIN
            IF OLD.is_current AND NOT NEW.is_current THEN
                UPDATE tax_cumulative_records
                   SET is_current = false
                 WHERE id = OLD.tax_cumulative_record_id
                   AND is_current;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'tax cumulative lifecycle is inconsistent';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_tax_sync_demote_cumulative
        AFTER UPDATE OF is_current ON payroll_tax_ledger_syncs
        FOR EACH ROW EXECUTE FUNCTION demote_superseded_tax_record()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_tax_sync_demote_cumulative "
        "ON payroll_tax_ledger_syncs"
    )
    op.execute("DROP FUNCTION IF EXISTS demote_superseded_tax_record()")
    op.execute("DROP TRIGGER IF EXISTS trg_synced_tax_run_immutable ON tax_calculation_runs")
    op.execute("DROP FUNCTION IF EXISTS protect_synced_tax_run()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_synced_tax_record_immutable "
        "ON tax_cumulative_records"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_synced_tax_record()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payroll_tax_sync_integrity "
        "ON payroll_tax_ledger_syncs"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_payroll_tax_sync()")
    op.drop_index("uq_tax_sync_current_period", table_name="payroll_tax_ledger_syncs")
    op.drop_index(
        "ix_tax_sync_employee_year_period", table_name="payroll_tax_ledger_syncs",
    )
    op.drop_index("ix_tax_sync_org_import", table_name="payroll_tax_ledger_syncs")
    op.drop_table("payroll_tax_ledger_syncs")
    op.drop_index(
        "uq_tax_cumulative_current_period", table_name="tax_cumulative_records",
    )
    op.drop_constraint(
        "uq_tax_cumulative_sync_scope", "tax_cumulative_records", type_="unique",
    )
    op.drop_constraint(
        "uq_tax_cumulative_supersedes_record", "tax_cumulative_records",
        type_="unique",
    )
    op.drop_constraint(
        "fk_tax_cumulative_supersedes", "tax_cumulative_records",
        type_="foreignkey",
    )
    op.drop_column("tax_cumulative_records", "supersedes_record_id")
    op.drop_column("tax_cumulative_records", "is_current")
    op.drop_constraint(
        "uq_tax_calc_run_sync_scope", "tax_calculation_runs", type_="unique",
    )
    op.drop_index(
        "ix_tax_calc_runs_payroll_version_id", table_name="tax_calculation_runs",
    )
    op.drop_constraint(
        "fk_tax_calc_run_payroll_version", "tax_calculation_runs",
        type_="foreignkey",
    )
    op.drop_column("tax_calculation_runs", "payroll_version_id")
    op.drop_constraint(
        "uq_materialization_tax_sync_scope", "payroll_import_materializations",
        type_="unique",
    )
