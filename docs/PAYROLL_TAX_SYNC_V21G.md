# Payroll Tax-Ledger Synchronization V2.1G

## Authoritative boundary

```text
authoritative ACTIVE/current PayrollVersion
  -> existing effective-dated TaxRuleSet and TaxEngine
  -> deterministic withholding reconciliation
  -> TaxCalculationRun + current TaxCumulativeRecord
  -> immutable PayrollTaxLedgerSync evidence
```

Tax synchronization reads financial truth only from the persisted
`PayrollVersion`. `Payroll` and `Employee` provide identity and period context.
The V2.1F materialization and approval chain is verified as provenance. OCR,
staging fields, mappings, source labels, filenames, requests, General Reader,
and LLM output are never tax inputs.

The POST request is empty. The service never changes approved snapshot data,
approval evidence, materialization evidence, or any `PayrollVersion` financial
value. It creates no earning, deduction, or absence detail rows.

## Deterministic calculation and reconciliation

The service resolves the active `TaxRuleSet` using the existing
`TaxService.resolve_rule_set()` effective-date semantics for the first day of
the payroll period. Missing rules or employment brackets fail closed; there is
no hardcoded fallback.

The existing `TaxEngine.calculate_progressive_tax()` computes cumulative gross
liability. The existing `CumulativeTaxService.calculate_monthly_withholding()`
computes:

```text
closing cumulative liability
- prior current cumulative liability
- supported exemptions (currently 0.00 in the existing domain)
```

All inputs and results remain `Decimal`. Calculation happens before any tax
row is persisted. The calculated withholding must exactly equal
`PayrollVersion.income_tax`; a mismatch raises
`TAX_SYNC_RECONCILIATION_FAILED` and writes no tax run, cumulative record, or
sync evidence. Tax sync never repairs the authoritative payroll.

## Tax-year and prior-period context

Prior context is scoped by organization, employee, and tax year. The latest
earlier authoritative ACTIVE/current PayrollVersion is selected without
requiring calendar-month continuity. Its current tax sync and cumulative
record must exist; otherwise synchronization fails with
`TAX_SYNC_PRIOR_PERIOD_REQUIRED`. With no earlier authoritative payroll in the
same year, opening cumulative base is `0.00`. Previous-year rows never carry
into January.

## Revision safety

`TaxCumulativeRecord.is_current` and `PayrollTaxLedgerSync.is_current` provide
explicit business selection. Partial unique indexes enforce at most one
current record and sync per employee/tax-year/period. Existing status and
dashboard reads use only current cumulative rows; creation time is not a
business selector.

When a same-period PayrollVersion revision becomes authoritative and no later
current synchronized period exists, V2.1G appends a new run, cumulative row,
and sync. The new cumulative row and sync point to the records they supersede.
The old rows remain historical; only the sync's `is_current` lifecycle marker
moves directly from true to false. An AFTER trigger performs the matching
current-to-historical transition on its exact cumulative record. Direct
cumulative lifecycle updates are rejected. `TaxCalculationRun` is fully
immutable after insertion. Cumulative values and sync provenance/evidence are
immutable; neither lifecycle flag can transition from historical to current.
Supersession lineage is validated when the replacement sync is inserted.

If a later current synchronized period exists, an earlier-period revision
fails with `TAX_SYNC_DOWNSTREAM_REBUILD_REQUIRED`. V2.1G never silently
recalculates or mutates downstream history. An explicit downstream rebuild is
a future workflow.

## Idempotency, transaction, and locking

One unique sync is allowed per materialization and PayrollVersion. A repeat
returns that exact existing result and creates no duplicate rows.

The service locks in this order:

1. employee (serializes all of that employee's tax-year chains);
2. payroll;
3. authoritative PayrollVersion;
4. same-period current sync and cumulative row.

This order serializes competing version and sequential-period writers. Unique
current-period indexes and composite provenance foreign keys provide the
independent database backstop. Verification, reconciliation, lifecycle
transition, run creation, cumulative creation, and evidence creation commit or
roll back as one transaction.

## API and access

- `POST /api/v1/payroll-imports/{id}/materialization/tax-sync` accepts only
  `{}`. `PAYROLL_ADMIN` may execute it.
- `GET /api/v1/payroll-imports/{id}/materialization/tax-sync` returns current
  or historical sync state. `PAYROLL_ADMIN`, `HR_ADMIN`, and `AUDITOR` may
  read it.
- `EMPLOYEE` and `SYSTEM_ADMIN` have no access. Cross-organization lookup is a
  non-disclosing 404.

Decimal response amounts are strings. The response identifies the exact
PayrollVersion, materialization, rule set, calculation run, cumulative record,
prior/superseded sync, reconciliation state, actor, and checksum.
