# Payroll Detail Mapping V2.1J

V2.1J turns the generic table evidence introduced in V2.1I into reviewed,
authoritative payroll detail rows. The boundary is:

```text
PayrollImportTable / Row / Cell
    -> deterministic mapping registry
    -> separate human correction evidence
    -> immutable reviewed detail snapshot
    -> approved PayrollImport evidence
    -> PayrollEarning / PayrollDeduction / PayrollAbsence
```

## Deterministic mapping

The Bordro-side `PayrollDetailMapping` registry matches normalized row labels and
explicit configured column IDs. It does not infer column roles from their
position. Precedence is template-specific, then organization-specific, then
system-wide; priority resolves matches within a scope. Equal best matches are
reported as `AMBIGUOUS`, and missing mappings remain `UNMAPPED`.

Supported effective types are `EARNING`, `DEDUCTION`, `ABSENCE`, and `UNMAPPED`.
Malformed numeric text is `PARSE_FAILED`. Values use the existing locale-aware
Decimal parser and are never converted through float.

## Review and readiness

Every extracted row requires explicit review, including deterministic matches.
A correction is append-only evidence and records the source checksum, effective
classification, canonical identity, values, reviewer, time, and reason. An
unmapped row may be omitted from authoritative details only when a reviewer
explicitly preserves it as ignored `UNMAPPED` evidence.

Optimistic row versions reject concurrent review writes. Source checksums are
recomputed from the live V2.1I table/row/cell evidence at correction,
finalization, approval, and materialization. Ambiguity, parse failures,
unreviewed rows, stale evidence, incomplete type-specific values, and duplicate
canonical identities fail closed.

## Snapshot and approval

Finalization freezes the effective rows, source identity and checksum,
correction lineage, reviewer evidence, and type-specific values in an immutable
snapshot. PostgreSQL triggers reject updates or deletes of corrections,
snapshots, snapshot rows, and materialization actions.

For an import containing staged table rows, the existing payroll approval must
bind the current detail snapshot ID and checksum. The established scalar
approval checksum remains byte-compatible for imports without tables. There is
no second approval lifecycle.

## Authoritative materialization

Detail materialization requires the existing approved scalar materialization and
targets that exact `PayrollVersion`. Each authoritative row is constrained back
to its organization, import, table, row, snapshot row, PayrollVersion, and
materialization action. One snapshot row can materialize only once, and one
detail action exists per scalar materialization, making retries idempotent.

Materialized detail rows are immutable. A later scalar PayrollVersion revision
owns a new detail set; older detail history is preserved.

This phase does not recalculate or overwrite any `PayrollVersion` financial,
tax, or total field. The authoritative PayrollVersion remains scalar financial
truth; V2.1J adds only its reviewed breakdown.

## Explicit exclusions

- No General Reader changes.
- No LLM classification.
- No OCR, MongoDB, template, tax-sync, or tax-rebuild changes.
- No payroll total or tax recalculation.
- No PayrollVersion financial mutation.
- No frontend, chatbot, or voice implementation.
