# Payroll Adapter V2.1B

## Boundary

```text
General Reader extraction
    -> PayrollImportField (immutable generic observation)
    -> PayrollAdapterService
    -> PayrollImportMappedField / PayrollImportMappingIssue
```

Canonical Review Mapping is not approved payroll. The adapter creates no
`PayrollVersion`, earning, deduction, absence, tax-run, or cumulative-tax
record. It performs no calculation, statutory validation, General Reader call,
or source-field mutation.

General Reader table staging remains deferred. Earnings/deductions row
materialization requires a later table-staging task. Unmapped scalar fields stay
in `PayrollImportField` and also receive queryable `UNMAPPED` review rows. This
keeps the design compatible with a future `PayrollDocumentField` snapshot.

## Registry and mapping resolution

`canonical_fields.py` owns the controlled Bordro registry. Every key targets an
existing model attribute and fixes its section, type, financial flag,
future-materialization requirement, and automatic-mapping permission. Database
constraints reject unknown keys; the service rejects configured section/type
disagreement.

PostgreSQL `payroll_field_mappings` is the runtime source of truth. Migration
V2.1B seeds only explicit, unabbreviated Turkish system aliases. In particular,
no `Dev.` alias is seeded. Organization and template aliases are supported by
the domain/repository; administration CRUD is deferred.

Precedence is exact-template/same-organization, then organization, then system.
Within the winning scope, highest numeric priority wins. Multiple active
candidates at that scope and priority are `AMBIGUOUS`; version or insertion
order never breaks a tie. Other-tenant, other-template, and inactive rows are
ineligible.

## Normalization and parsing

Labels are NFKC-normalized; Unicode dash/apostrophe variants are canonicalized;
Turkish `I/İ` lowercasing is explicit; `. , : ;` become separators; whitespace
is collapsed; final storage is NFC. Semantic punctuation such as `/`, `%`, `+`,
`-`, and `&` stays distinct. Normalization locates configured mappings only and
never assigns business meaning.

Types are `DECIMAL`, `INTEGER`, `DAY_COUNT`, `DATE`, `TEXT`, and `IDENTIFIER`.
Decimal/day parsing uses `Decimal` only, accepts validated Turkish or canonical
formatting, enforces `NUMERIC(18,2)`, and rejects ambiguous single separators
with three trailing digits. Dates accept ISO `YYYY-MM-DD` and Turkish
`DD.MM.YYYY`. Failure yields `PARSE_FAILED`, never zero/default.

## Review and repeat runs

Each source produces one result: `MAPPED`, `UNMAPPED`, `AMBIGUOUS`, or
`PARSE_FAILED`. Safe mapping/parsing is at most `UNREVIEWED`, never verified or
approved. Existing source warnings, confidence below 0.80, LLM extraction,
ambiguity, and parse errors require review. Required concepts without a safe
parsed source create separate `MISSING` issues, not fake source rows.

Each run locks the organization-scoped import and transactionally replaces only
adapter-owned rows/issues, so unchanged staging cannot accumulate duplicates.
No correction UI exists; future human corrections must be stored separately and
excluded from replacement.

Mapping is permitted only for `EXTRACTED` or `REVIEW_REQUIRED` imports. It does
not alter the extraction-oriented `PayrollImport.status`.

## API and access

| Method | Route | PAYROLL/HR admin | Auditor |
|---|---|---:|---:|
| POST | `/api/v1/payroll-imports/{id}/map` | run | denied |
| GET | `/api/v1/payroll-imports/{id}/mapped-fields` | read | read |
| GET | `/api/v1/payroll-imports/{id}/mapping-summary` | read | read |

Employees and system administrators have no implicit access. All lookups are
organization-scoped, and cross-organization identifiers return 404. Decimal API
values serialize as strings.
