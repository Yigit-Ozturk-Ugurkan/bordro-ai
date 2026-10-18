# Payroll Validation V2.1D

## Boundary and flow

V2.1D adds this bounded workflow:

```text
immutable reviewed snapshot
  -> deterministic code-owned validation rules
  -> immutable versioned validation run and results
  -> READY_FOR_FUTURE_APPROVAL or NOT_READY
  -> future approval phase
```

The immutable `PayrollImportReviewSnapshot` and its snapshot fields are the
only imported payroll values supplied to business validation. Employee and
existing-current-payroll queries provide organization-scoped reference
context; mutable staging, adapter mappings, and corrections are not validation
inputs.

Validation is not approval, publication, or `PayrollVersion` materialization.
It does not alter reviewed values, create corrections, call an LLM or General
Reader, rerun OCR, or create tax calculation/cumulative ledger records.

## Rules and versions

Rules are registered in code with a stable code, rule version, category,
default severity, required canonical inputs, description, and callable. The
initial ruleset version is `1`.

- `REQUIRED_CANONICAL_FIELDS:v1` blocks missing required registry concepts.
- `DUPLICATE_CANONICAL_FIELDS:v1` blocks duplicate canonical scalars.
- `SNAPSHOT_VALUE_TYPES:v1` blocks invalid canonical types or storage shapes.
- `EMPLOYEE_IDENTITY:v1` resolves only exact same-organization employee numbers.
- `PERIOD_VALIDITY:v1` blocks years outside 1..9999 or months outside 1..12.
- `EXISTING_PAYROLL_PERIOD:v1` warns when a current payroll already exists.
- `NET_PAY_RECONCILIATION:v1` uses exact `Decimal` subtraction and equality.
- Earning-detail and deduction-detail reconciliation emit INFO/NOT_APPLICABLE
  because reviewed table rows do not exist in the current staging model.
- Tax, cumulative-tax, stamp-tax, and SGK reconciliation emit
  INFO/NOT_APPLICABLE. Existing orchestration persists calculation and ledger
  records, so it is not safe for this side-effect-free phase. No statutory
  assumptions are substituted.

`ERROR` and `BLOCKING` results block future approval readiness. `WARNING` and
`INFO` do not. Readiness is derived only after successful rule execution and
does not grant approval.

## Durability, integrity, and idempotency

Runs retain snapshot checksum, ruleset/run versions, counts, execution status,
actor, timestamps, and a deterministic result checksum. Results retain stable
rule metadata, typed comparison strings, related snapshot field IDs, and JSON
details.

The result checksum is SHA-256 over UTF-8 canonical JSON. Object keys and
results are sorted, IDs/timestamps belonging to the run are excluded, and
financial values are exact decimal strings.

The database rejects mutation/deletion of completed runs and mutation/deletion
of individual results. Revalidating the same snapshot with the same ruleset
returns the existing completed run. A new ruleset version produces a new run;
historical results are never rewritten.

## API and access

- `POST /api/v1/payroll-imports/{id}/review/snapshots/{snapshot_id}/validate`
- `GET /api/v1/payroll-imports/{id}/validations`
- `GET /api/v1/payroll-imports/{id}/validations/{run_id}`

Payroll and HR administrators may validate and read. Auditors may read only.
Employees and system administrators have no implicit access. Every lookup is
organization-scoped and cross-organization identifiers receive a
non-disclosing not-found response.
