# Payroll Tax Ledger Rebuild V2.1H

V2.1H adds an explicit, audited, versioned workflow for rebuilding an
employee's cumulative tax chain after an earlier authoritative payroll
revision.

## Safety boundary

The normal V2.1G tax-sync endpoint still rejects an earlier-period revision
when later synchronized periods exist. It never starts a cascade. A payroll
administrator must first create a rebuild plan, inspect its persisted preview,
and then call the separate execute endpoint.

The flow is:

```text
historical payroll revision
  -> normal tax sync blocks the downstream conflict
  -> PAYROLL_ADMIN creates a deterministic rebuild plan
  -> PAYROLL_ADMIN reviews the affected periods
  -> PAYROLL_ADMIN explicitly executes the plan
  -> periods recalculate sequentially in one tax year
  -> new current tax evidence supersedes the old chain
  -> all old tax evidence remains immutable history
```

There is no silent cascade, no PayrollVersion correction, no OCR/LLM work,
and no cross-tax-year rebuild. A failure rolls back the entire tax-chain
execution.

## Durable evidence

`PayrollTaxLedgerRebuild` records the organization, employee, tax year,
trigger import/materialization/payroll/version and period, prior opening
context, status, planning and execution actors, timestamps, deterministic plan
checksum, result checksum, and sanitized failure evidence.

`PayrollTaxLedgerRebuildItem` records each exact authoritative
PayrollVersion in period order, its import/materialization provenance, the old
current sync and cumulative record, the effective ruleset and ruleset
fingerprint, a complete PayrollVersion fingerprint, and the new run/sync/record
IDs produced by successful execution.

The states are `PLANNED`, `RUNNING`, `COMPLETED`, and `FAILED`. Database
triggers permit only controlled lifecycle transitions and reject deletes or
changes to plan/evidence fields. Completed and failed evidence is immutable.

## Planning and staleness

Planning starts at the active current trigger PayrollVersion and selects active
current PayrollVersions for the same organization, employee, and tax year from
that period onward. Ordering is by payroll month, never creation time. Missing
calendar months are not fabricated. A partial unique index permits only one
`PLANNED` or `RUNNING` plan per employee/tax-year chain.

The SHA-256 plan checksum covers stable organization/employee/year identity,
the trigger version, exact prior context, and the ordered item evidence. It
excludes timestamps.

Before execution, the service locks the employee chain and verifies:

- the trigger and every planned PayrollVersion remain active and current;
- the exact ordered version/materialization set is unchanged;
- no additional affected authoritative period has appeared;
- every old current sync, cumulative record, and sync checksum still matches;
- the opening prior sync/record/checksum still matches;
- every PayrollVersion financial and provenance fingerprint still matches;
- effective ruleset identity, version, effective dates, and bracket fingerprint
  still match;
- the stored plan checksum still verifies.

Any mismatch fails with `TAX_REBUILD_PLAN_STALE`. The stored plan is never
silently rewritten; a new plan is required.

## Atomic execution

Execution locks in the common order employee, rebuild plan, ordered
payroll/version rows, then effective tax-rule rows. Normal tax sync and payroll
materialization already use the same employee lock, so they cannot interleave
chain writes with an executing rebuild.

The opening cumulative context is the exact current cumulative record
immediately before the trigger period. If no earlier payroll exists in the tax
year, existing new-year zero semantics apply. If an earlier authoritative
period exists but its current tax context is missing, execution fails closed.

For every persisted item, the service uses the existing `TaxService`,
`TaxEngine`, and `CumulativeTaxService` to calculate from the newly rebuilt
previous closing context. The calculated withholding must equal the immutable
current `PayrollVersion.income_tax`. It then appends a new
`TaxCalculationRun`, `TaxCumulativeRecord`, and `PayrollTaxLedgerSync`, with
explicit same-period supersession links. Only the V2.1G controlled lifecycle
transition makes the old sync/record historical.

All periods execute in one database transaction. If any period fails, every
new run, cumulative record, sync, item result, and lifecycle demotion is rolled
back. A separate sanitized `FAILED` lifecycle update preserves the failed-plan
audit outcome; failed plans are not retried or rewritten.

A completed plan is idempotent: executing it again returns its existing result
without creating tax records. After success, each affected employee/year/month
has exactly one current sync and one current cumulative record.

## API and authorization

- `POST /api/v1/payroll-imports/{id}/materialization/tax-rebuilds` creates and
  previews a plan from an empty body.
- `GET /api/v1/payroll-imports/{id}/materialization/tax-rebuilds` lists plans.
- `GET /api/v1/payroll-imports/{id}/materialization/tax-rebuilds/{rebuild_id}`
  reads one plan and its items.
- `POST /api/v1/payroll-imports/{id}/materialization/tax-rebuilds/{rebuild_id}/execute`
  explicitly executes a plan from an empty body.

Only `PAYROLL_ADMIN` may create or execute. `PAYROLL_ADMIN`, `HR_ADMIN`, and
`AUDITOR` may read. `EMPLOYEE` and `SYSTEM_ADMIN` have no access. Every lookup
is organization-scoped; cross-organization IDs return a non-disclosing 404.

The browser submits no employee, period, version, ruleset, rate, base, tax, or
withholding values. All business inputs come from the persisted plan and
authoritative server-side domain state.

## Source immutability

Rebuild execution never updates PayrollVersion financial values, including
earnings, tax and contribution bases, employee deductions, taxes, totals, net
pay, paid days, or missing days. It does not update review, correction,
snapshot, validation, warning acknowledgement, approval, materialization,
mapping, staging, import-document, or reader evidence.
