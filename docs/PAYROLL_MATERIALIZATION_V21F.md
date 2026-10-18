# Payroll Materialization V2.1F

## Evidence boundary

V2.1F introduces the first authoritative write from the import workflow:

```text
current immutable review snapshot
  -> exact completed READY validation run
  -> exact immutable APPROVED decision
  -> one atomic materialization transaction
  -> Payroll / ACTIVE current PayrollVersion
```

Materialization reads business values only from typed fields in the immutable
review snapshot. It does not read OCR fields, generic staging rows, current
adapter output, source labels, filenames, or request-supplied payroll values.
The request identifies only the immutable approval.

## Authoritative version semantics

The existing domain treats `is_current` as the authoritative version selector
and `ACTIVE` as the published/current status. Materialization therefore creates
an `ACTIVE`, current, `IMPORTED` PayrollVersion. If the employee/period has no
Payroll, it creates the Payroll container and revision 1. Otherwise it locks
the existing Payroll, allocates `max(revision_no) + 1`, clears the former
current flag, and changes a former current `ACTIVE` version to `SUPERSEDED`.

Employee locking serializes the case where no Payroll row exists yet. Payroll
and current-version locks serialize revision allocation. Unique constraints
independently enforce employee/period identity, revision identity, one current
version, and one materialization per approval.

The new PayrollVersion stores `source_import_id` and the immutable review
snapshot checksum as `source_checksum`. A foreign key now protects the source
import reference. Materialization from the document-import pipeline uses the
generic `DOCUMENT` source class for every supported document format. Exact
filename, extension, declared MIME, and detected MIME remain on
`PayrollImportDocument`; exact lifecycle provenance comes from
`source_import_id` and materialization evidence.

## Canonical field copy

These exact canonical keys are copied without recalculation:

- `gross_earnings` -> `PayrollVersion.gross_earnings`
- `sgk_base` -> `PayrollVersion.sgk_base`
- `income_tax_base` -> `PayrollVersion.income_tax_base`
- `stamp_tax_base` -> `PayrollVersion.stamp_tax_base`
- `employee_sgk` -> `PayrollVersion.employee_sgk`
- `employee_unemployment` -> `PayrollVersion.employee_unemployment`
- `income_tax` -> `PayrollVersion.income_tax`
- `stamp_tax` -> `PayrollVersion.stamp_tax`
- `total_earnings` -> `PayrollVersion.total_earnings`
- `total_deductions` -> `PayrollVersion.total_deductions`
- `net_pay` -> `PayrollVersion.net_pay`
- `paid_days` -> `PayrollVersion.paid_days`
- `missing_days` -> `PayrollVersion.missing_days`

`employee_identifier`, `period_year`, and `period_month` resolve Payroll
identity. Every required key must occur exactly once with its registry-defined
type. Financial/day values must already be finite `Decimal` values exactly
representable by the target `NUMERIC` precision and scale. Missing, duplicate,
wrongly typed, or out-of-range data fails closed. Generic unmapped fields and
`cumulative_income_tax_base` remain only in the immutable snapshot.

Materialization does not recalculate net pay, tax, tax bases, SGK, stamp tax,
or deductions. It copies approved reviewed facts exactly.

## Evidence verification and idempotency

Before writing, the service verifies the current snapshot/latest-ruleset
context through the V2.1E resolver and checks:

- organization, import, snapshot, validation run, and ruleset identity;
- completed status and READY severities;
- snapshot and validation checksums across the persisted chain;
- recomputed validation-result checksum and stored result counts;
- persisted warning acknowledgements and acknowledged-warning IDs;
- recomputed approval checksum and `APPROVED` decision;
- snapshot field count and zero snapshot issues.

Historical approval for an older snapshot or ruleset cannot create a new
materialization. A rejected decision cannot materialize.

`PayrollImportMaterialization` immutably binds the approval, snapshot,
validation, Payroll, PayrollVersion, revision, all evidence checksums, server
actor, and a deterministic materialization checksum. A unique approval key
makes materialization exactly-once. Repeating an already materialized approval
returns its existing evidence and version without creating another revision.
Materialization does not mutate the approval to a consumed state.

## Atomicity and side effects

Evidence verification, Payroll creation/lookup, supersession, revision
creation, provenance, and materialization evidence are committed together or
rolled back together.

Materialization does not rerun OCR or General Reader. It does not invoke the
adapter, an LLM, tax calculation, or tax-ledger synchronization. It does not
create PayrollEarning, PayrollDeduction, or PayrollAbsence rows from scalar
totals. Approved source evidence remains immutable.

## API and access

- `POST /api/v1/payroll-imports/{id}/approvals/{approval_id}/materialize`
  accepts only an empty object and returns authoritative/materialization IDs,
  revision, status, employee, period, checksum, actor, and timestamp.
- `GET /api/v1/payroll-imports/{id}/materialization` reports materialization
  for the current approval context.

`PAYROLL_ADMIN` may materialize and read. `HR_ADMIN` and `AUDITOR` are
read-only. `EMPLOYEE` is denied. `SYSTEM_ADMIN` has no implicit access. All
lookups are organization-scoped and cross-organization access is
non-disclosing.
