"""add explicit versioned payroll tax ledger rebuilds

Revision ID: d9e5f7a1b203
Revises: c8d4e6f8a102
Create Date: 2026-09-08 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e5f7a1b203"
down_revision: Union[str, Sequence[str], None] = "c8d4e6f8a102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _install_sync_integrity_function(*, rebuild_aware: bool) -> None:
    version_match = "" if rebuild_aware else (
        "AND old_sync.payroll_version_id <> NEW.payroll_version_id"
    )
    history_match = "" if rebuild_aware else (
        "AND old_sync.payroll_version_id <> NEW.payroll_version_id"
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION enforce_payroll_tax_sync() RETURNS trigger AS $$
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
                   {version_match}
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
                   {history_match}
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


def upgrade() -> None:
    op.drop_constraint(
        "uq_tax_sync_materialization", "payroll_tax_ledger_syncs", type_="unique",
    )
    op.drop_constraint(
        "uq_tax_sync_payroll_version", "payroll_tax_ledger_syncs", type_="unique",
    )
    op.create_index(
        "ix_tax_sync_materialization", "payroll_tax_ledger_syncs",
        ["materialization_id"],
    )
    op.create_index(
        "ix_tax_sync_payroll_version", "payroll_tax_ledger_syncs",
        ["payroll_version_id"],
    )
    _install_sync_integrity_function(rebuild_aware=True)

    op.create_table(
        "payroll_tax_ledger_rebuilds",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("trigger_payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("trigger_materialization_id", sa.UUID(), nullable=False),
        sa.Column("trigger_payroll_id", sa.UUID(), nullable=False),
        sa.Column("trigger_payroll_version_id", sa.UUID(), nullable=False),
        sa.Column("trigger_period_year", sa.Integer(), nullable=False),
        sa.Column("trigger_period_month", sa.Integer(), nullable=False),
        sa.Column("prior_sync_id", sa.UUID(), nullable=True),
        sa.Column("prior_cumulative_record_id", sa.UUID(), nullable=True),
        sa.Column("prior_sync_result_checksum", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("executed_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_checksum", sa.String(64), nullable=False),
        sa.Column("result_checksum", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("tax_year >= 2000", name="ck_tax_rebuild_year_valid"),
        sa.CheckConstraint(
            "trigger_period_year = tax_year", name="ck_tax_rebuild_trigger_tax_year",
        ),
        sa.CheckConstraint(
            "trigger_period_month BETWEEN 1 AND 12", name="ck_tax_rebuild_trigger_month",
        ),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_tax_rebuild_status",
        ),
        sa.CheckConstraint("length(plan_checksum) = 64", name="ck_tax_rebuild_plan_checksum"),
        sa.CheckConstraint(
            "prior_sync_result_checksum IS NULL OR "
            "length(prior_sync_result_checksum) = 64",
            name="ck_tax_rebuild_prior_checksum",
        ),
        sa.CheckConstraint(
            "(prior_sync_id IS NULL) = (prior_cumulative_record_id IS NULL) "
            "AND (prior_sync_id IS NULL) = "
            "(prior_sync_result_checksum IS NULL)",
            name="ck_tax_rebuild_prior_evidence_complete",
        ),
        sa.CheckConstraint(
            "result_checksum IS NULL OR length(result_checksum) = 64",
            name="ck_tax_rebuild_result_checksum",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trigger_payroll_id"], ["payrolls.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trigger_payroll_version_id"], ["payroll_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_sync_id"], ["payroll_tax_ledger_syncs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_cumulative_record_id"], ["tax_cumulative_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["trigger_payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_tax_rebuild_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_materialization_id", "organization_id",
             "trigger_payroll_id", "trigger_payroll_version_id"],
            ["payroll_import_materializations.id",
             "payroll_import_materializations.organization_id",
             "payroll_import_materializations.payroll_id",
             "payroll_import_materializations.payroll_version_id"],
            name="fk_tax_rebuild_materialization_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tax_rebuild_org_import_created", "payroll_tax_ledger_rebuilds",
        ["organization_id", "trigger_payroll_import_id", "created_at"],
    )
    op.create_index(
        "uq_tax_rebuild_actionable_chain", "payroll_tax_ledger_rebuilds",
        ["organization_id", "employee_id", "tax_year"], unique=True,
        postgresql_where=sa.text("status IN ('PLANNED', 'RUNNING')"),
    )

    op.create_table(
        "payroll_tax_ledger_rebuild_items",
        sa.Column("rebuild_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("materialization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_id", sa.UUID(), nullable=False),
        sa.Column("payroll_version_id", sa.UUID(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("old_tax_sync_id", sa.UUID(), nullable=True),
        sa.Column("old_cumulative_record_id", sa.UUID(), nullable=True),
        sa.Column("old_sync_result_checksum", sa.String(64), nullable=True),
        sa.Column("ruleset_id", sa.UUID(), nullable=False),
        sa.Column("ruleset_version", sa.String(100), nullable=False),
        sa.Column("ruleset_checksum", sa.String(64), nullable=False),
        sa.Column("payroll_version_checksum", sa.String(64), nullable=False),
        sa.Column("execution_status", sa.String(20), nullable=False),
        sa.Column("new_tax_calculation_run_id", sa.UUID(), nullable=True),
        sa.Column("new_tax_sync_id", sa.UUID(), nullable=True),
        sa.Column("new_cumulative_record_id", sa.UUID(), nullable=True),
        sa.Column("reconciliation_status", sa.String(20), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_tax_rebuild_item_sequence"),
        sa.CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_tax_rebuild_item_month"),
        sa.CheckConstraint(
            "execution_status IN ('PENDING', 'COMPLETED')",
            name="ck_tax_rebuild_item_status",
        ),
        sa.CheckConstraint("length(payroll_version_checksum) = 64", name="ck_tax_rebuild_item_version_checksum"),
        sa.CheckConstraint("length(ruleset_checksum) = 64", name="ck_tax_rebuild_item_ruleset_checksum"),
        sa.CheckConstraint(
            "old_sync_result_checksum IS NULL OR "
            "length(old_sync_result_checksum) = 64",
            name="ck_tax_rebuild_item_old_checksum",
        ),
        sa.ForeignKeyConstraint(["rebuild_id"], ["payroll_tax_ledger_rebuilds.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payroll_import_id"], ["payroll_imports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["materialization_id"], ["payroll_import_materializations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payroll_id"], ["payrolls.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payroll_version_id"], ["payroll_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["old_tax_sync_id"], ["payroll_tax_ledger_syncs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["old_cumulative_record_id"], ["tax_cumulative_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ruleset_id"], ["tax_rule_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["new_tax_calculation_run_id"], ["tax_calculation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["new_tax_sync_id"], ["payroll_tax_ledger_syncs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["new_cumulative_record_id"], ["tax_cumulative_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rebuild_id", "sequence", name="uq_tax_rebuild_item_sequence"),
        sa.UniqueConstraint("rebuild_id", "payroll_version_id", name="uq_tax_rebuild_item_version"),
    )
    op.create_index(
        "ix_tax_rebuild_item_order", "payroll_tax_ledger_rebuild_items",
        ["rebuild_id", "sequence"],
    )

    op.execute("""
        CREATE FUNCTION enforce_tax_rebuild_header() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'tax rebuild evidence is immutable';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'PLANNED' OR NEW.started_at IS NOT NULL
                   OR NEW.completed_at IS NOT NULL
                   OR NEW.executed_by_user_id IS NOT NULL
                   OR NEW.result_checksum IS NOT NULL
                   OR NEW.failure_code IS NOT NULL
                   OR NEW.failure_message IS NOT NULL THEN
                    RAISE EXCEPTION 'new tax rebuild must be planned';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM employees employee
                      JOIN users creator ON creator.id = NEW.created_by_user_id
                      JOIN payroll_import_materializations materialization
                        ON materialization.id = NEW.trigger_materialization_id
                      JOIN payroll_versions version
                        ON version.id = NEW.trigger_payroll_version_id
                      JOIN payrolls payroll ON payroll.id = NEW.trigger_payroll_id
                     WHERE employee.id = NEW.employee_id
                       AND employee.organization_id = NEW.organization_id
                       AND creator.organization_id = NEW.organization_id
                       AND materialization.organization_id = NEW.organization_id
                       AND materialization.payroll_import_id = NEW.trigger_payroll_import_id
                       AND materialization.payroll_id = NEW.trigger_payroll_id
                       AND materialization.payroll_version_id = NEW.trigger_payroll_version_id
                       AND version.payroll_id = NEW.trigger_payroll_id
                       AND version.status = 'ACTIVE' AND version.is_current
                       AND payroll.organization_id = NEW.organization_id
                       AND payroll.employee_id = NEW.employee_id
                       AND payroll.period_year = NEW.tax_year
                       AND payroll.period_year = NEW.trigger_period_year
                       AND payroll.period_month = NEW.trigger_period_month
                ) THEN
                    RAISE EXCEPTION 'tax rebuild trigger provenance is invalid';
                END IF;
                IF NEW.prior_sync_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM payroll_tax_ledger_syncs prior_sync
                      JOIN tax_cumulative_records prior_record
                        ON prior_record.id = NEW.prior_cumulative_record_id
                     WHERE prior_sync.id = NEW.prior_sync_id
                       AND prior_sync.organization_id = NEW.organization_id
                       AND prior_sync.employee_id = NEW.employee_id
                       AND prior_sync.tax_year = NEW.tax_year
                       AND prior_sync.period_month < NEW.trigger_period_month
                       AND prior_sync.tax_cumulative_record_id = prior_record.id
                       AND prior_sync.result_checksum = NEW.prior_sync_result_checksum
                       AND prior_sync.is_current AND prior_record.is_current
                ) THEN
                    RAISE EXCEPTION 'tax rebuild prior provenance is invalid';
                END IF;
                RETURN NEW;
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status', 'executed_by_user_id',
                    'started_at', 'completed_at', 'result_checksum',
                    'failure_code', 'failure_message']) <>
               (to_jsonb(OLD) - ARRAY['status', 'executed_by_user_id',
                    'started_at', 'completed_at', 'result_checksum',
                    'failure_code', 'failure_message']) THEN
                RAISE EXCEPTION 'tax rebuild evidence is immutable';
            END IF;
            IF OLD.status = 'PLANNED' AND NEW.status = 'RUNNING'
               AND NEW.executed_by_user_id IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM users actor
                    WHERE actor.id = NEW.executed_by_user_id
                      AND actor.organization_id = NEW.organization_id
               )
               AND NEW.started_at IS NOT NULL
               AND NEW.completed_at IS NULL AND NEW.result_checksum IS NULL
               AND NEW.failure_code IS NULL AND NEW.failure_message IS NULL THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'RUNNING' AND NEW.status = 'COMPLETED'
               AND NEW.executed_by_user_id = OLD.executed_by_user_id
               AND NEW.started_at = OLD.started_at
               AND NEW.completed_at IS NOT NULL
               AND NEW.result_checksum IS NOT NULL
               AND NEW.failure_code IS NULL AND NEW.failure_message IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM payroll_tax_ledger_rebuild_items item
                    WHERE item.rebuild_id = OLD.id
                      AND item.execution_status <> 'COMPLETED'
               ) THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'PLANNED' AND NEW.status = 'FAILED'
               AND NEW.executed_by_user_id IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM users actor
                    WHERE actor.id = NEW.executed_by_user_id
                      AND actor.organization_id = NEW.organization_id
               )
               AND NEW.started_at IS NULL AND NEW.completed_at IS NOT NULL
               AND NEW.result_checksum IS NULL
               AND NEW.failure_code IS NOT NULL
               AND NEW.failure_message IS NOT NULL THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'tax rebuild lifecycle transition is invalid';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_tax_rebuild_header_integrity
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_tax_ledger_rebuilds
        FOR EACH ROW EXECUTE FUNCTION enforce_tax_rebuild_header()
    """)
    op.execute("""
        CREATE FUNCTION enforce_tax_rebuild_item() RETURNS trigger AS $$
        DECLARE parent payroll_tax_ledger_rebuilds%ROWTYPE;
        BEGIN
            SELECT * INTO parent FROM payroll_tax_ledger_rebuilds
             WHERE id = COALESCE(NEW.rebuild_id, OLD.rebuild_id);
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'tax rebuild item evidence is immutable';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF parent.status <> 'PLANNED'
                   OR NEW.execution_status <> 'PENDING'
                   OR NEW.new_tax_calculation_run_id IS NOT NULL
                   OR NEW.new_tax_sync_id IS NOT NULL
                   OR NEW.new_cumulative_record_id IS NOT NULL
                   OR NEW.reconciliation_status IS NOT NULL
                   OR NEW.completed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'new tax rebuild item must be pending';
                END IF;
                IF NEW.period_year <> parent.tax_year
                   OR NEW.period_month < parent.trigger_period_month
                   OR (NEW.old_tax_sync_id IS NULL) <>
                      (NEW.old_cumulative_record_id IS NULL)
                   OR (NEW.old_tax_sync_id IS NULL) <>
                      (NEW.old_sync_result_checksum IS NULL)
                   OR NOT EXISTS (
                       SELECT 1 FROM payroll_import_materializations materialization
                         JOIN payroll_versions version
                           ON version.id = NEW.payroll_version_id
                         JOIN payrolls payroll ON payroll.id = NEW.payroll_id
                         JOIN tax_rule_sets ruleset ON ruleset.id = NEW.ruleset_id
                        WHERE materialization.id = NEW.materialization_id
                          AND materialization.organization_id = parent.organization_id
                          AND materialization.payroll_import_id = NEW.payroll_import_id
                          AND materialization.payroll_id = NEW.payroll_id
                          AND materialization.payroll_version_id = NEW.payroll_version_id
                          AND version.payroll_id = NEW.payroll_id
                          AND version.source_import_id = NEW.payroll_import_id
                          AND version.source_checksum = materialization.snapshot_checksum
                          AND version.status = 'ACTIVE' AND version.is_current
                          AND payroll.organization_id = parent.organization_id
                          AND payroll.employee_id = parent.employee_id
                          AND payroll.period_year = parent.tax_year
                          AND payroll.period_month = NEW.period_month
                          AND ruleset.version = NEW.ruleset_version
                   ) THEN
                    RAISE EXCEPTION 'tax rebuild item provenance is invalid';
                END IF;
                IF NEW.old_tax_sync_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM payroll_tax_ledger_syncs old_sync
                      JOIN tax_cumulative_records old_record
                        ON old_record.id = NEW.old_cumulative_record_id
                     WHERE old_sync.id = NEW.old_tax_sync_id
                       AND old_sync.organization_id = parent.organization_id
                       AND old_sync.employee_id = parent.employee_id
                       AND old_sync.tax_year = parent.tax_year
                       AND old_sync.period_month = NEW.period_month
                       AND old_sync.tax_cumulative_record_id = old_record.id
                       AND old_sync.result_checksum = NEW.old_sync_result_checksum
                       AND old_sync.is_current AND old_record.is_current
                ) THEN
                    RAISE EXCEPTION 'tax rebuild old-current evidence is invalid';
                END IF;
                RETURN NEW;
            END IF;
            IF (to_jsonb(NEW) - ARRAY['execution_status',
                    'new_tax_calculation_run_id', 'new_tax_sync_id',
                    'new_cumulative_record_id', 'reconciliation_status',
                    'completed_at']) <>
               (to_jsonb(OLD) - ARRAY['execution_status',
                    'new_tax_calculation_run_id', 'new_tax_sync_id',
                    'new_cumulative_record_id', 'reconciliation_status',
                    'completed_at']) THEN
                RAISE EXCEPTION 'tax rebuild item evidence is immutable';
            END IF;
            IF parent.status = 'RUNNING'
               AND OLD.execution_status = 'PENDING'
               AND NEW.execution_status = 'COMPLETED'
               AND NEW.new_tax_calculation_run_id IS NOT NULL
               AND NEW.new_tax_sync_id IS NOT NULL
               AND NEW.new_cumulative_record_id IS NOT NULL
               AND NEW.reconciliation_status = 'MATCHED'
               AND NEW.completed_at IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM payroll_tax_ledger_syncs sync
                     JOIN tax_calculation_runs run
                       ON run.id = NEW.new_tax_calculation_run_id
                     JOIN tax_cumulative_records record
                       ON record.id = NEW.new_cumulative_record_id
                    WHERE sync.id = NEW.new_tax_sync_id
                      AND sync.organization_id = parent.organization_id
                      AND sync.employee_id = parent.employee_id
                      AND sync.tax_year = parent.tax_year
                      AND sync.period_month = NEW.period_month
                      AND sync.payroll_id = NEW.payroll_id
                      AND sync.payroll_version_id = NEW.payroll_version_id
                      AND sync.tax_calculation_run_id = run.id
                      AND sync.tax_cumulative_record_id = record.id
                      AND sync.supersedes_sync_id IS NOT DISTINCT FROM NEW.old_tax_sync_id
                      AND record.supersedes_record_id IS NOT DISTINCT FROM NEW.old_cumulative_record_id
                      AND sync.is_current AND record.is_current
               ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'tax rebuild item evidence is immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_tax_rebuild_item_integrity
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_tax_ledger_rebuild_items
        FOR EACH ROW EXECUTE FUNCTION enforce_tax_rebuild_item()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM payroll_tax_ledger_rebuilds) THEN
                RAISE EXCEPTION
                    'cannot downgrade while payroll tax rebuild evidence exists';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_tax_rebuild_item_integrity ON payroll_tax_ledger_rebuild_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_tax_rebuild_item()")
    op.execute("DROP TRIGGER IF EXISTS trg_tax_rebuild_header_integrity ON payroll_tax_ledger_rebuilds")
    op.execute("DROP FUNCTION IF EXISTS enforce_tax_rebuild_header()")
    op.drop_index("ix_tax_rebuild_item_order", table_name="payroll_tax_ledger_rebuild_items")
    op.drop_table("payroll_tax_ledger_rebuild_items")
    op.drop_index("uq_tax_rebuild_actionable_chain", table_name="payroll_tax_ledger_rebuilds")
    op.drop_index("ix_tax_rebuild_org_import_created", table_name="payroll_tax_ledger_rebuilds")
    op.drop_table("payroll_tax_ledger_rebuilds")
    _install_sync_integrity_function(rebuild_aware=False)
    op.drop_index("ix_tax_sync_payroll_version", table_name="payroll_tax_ledger_syncs")
    op.drop_index("ix_tax_sync_materialization", table_name="payroll_tax_ledger_syncs")
    op.create_unique_constraint(
        "uq_tax_sync_payroll_version", "payroll_tax_ledger_syncs",
        ["payroll_version_id"],
    )
    op.create_unique_constraint(
        "uq_tax_sync_materialization", "payroll_tax_ledger_syncs",
        ["materialization_id"],
    )
